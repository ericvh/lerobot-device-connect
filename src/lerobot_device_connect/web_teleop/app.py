"""FastAPI application for browser-based LeKiwi teleop."""

from __future__ import annotations

import asyncio
import base64
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lerobot_device_connect.device_connect_invoker import DeviceConnectRpcError
from lerobot_device_connect.web_teleop.session import RobotSession

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
MJPEG_BOUNDARY = b"frame"


class DriveBaseRequest(BaseModel):
    direction: str


class DriveBaseKeysRequest(BaseModel):
    keys: list[str] = Field(default_factory=list)


class ArmJointRequest(BaseModel):
    joint: str
    position: float | None = None
    delta: float | None = None


def create_app(session: RobotSession, *, fps: float = 8.0) -> FastAPI:
    frame_interval = 1.0 / max(fps, 1.0)

    async def call_rpc(method: str, **params: Any) -> dict[str, Any]:
        try:
            return await session.rpc(method, **params)
        except DeviceConnectRpcError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await session.connect()
        yield
        await session.disconnect()

    app = FastAPI(
        title="LeRobot Web Teleop",
        description="Browser UI for LeKiwi base and arm control with camera feeds.",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/connection")
    async def connection() -> dict[str, str]:
        return {"mode": session.mode_label}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        result = await call_rpc("get_status")
        result["connection_mode"] = session.mode_label
        return result

    @app.get("/api/features")
    async def features() -> dict[str, Any]:
        return await call_rpc("get_features")

    @app.get("/api/arm/config")
    async def arm_config() -> dict[str, Any]:
        return await call_rpc("get_arm_config")

    @app.get("/api/arm/positions")
    async def arm_positions() -> dict[str, Any]:
        return await call_rpc("get_arm_positions")

    @app.post("/api/arm/joint")
    async def arm_joint(body: ArmJointRequest) -> dict[str, Any]:
        if body.delta is not None:
            return await call_rpc("nudge_arm_joint", joint=body.joint, delta=body.delta)
        if body.position is not None:
            return await call_rpc("set_arm_joint", joint=body.joint, position=body.position)
        raise HTTPException(status_code=400, detail="provide position or delta")

    @app.get("/api/base/config")
    async def base_config() -> dict[str, Any]:
        return await call_rpc("get_base_teleop_config")

    @app.post("/api/base/drive")
    async def base_drive(body: DriveBaseRequest) -> dict[str, Any]:
        return await call_rpc("drive_base", direction=body.direction)

    @app.post("/api/base/drive-keys")
    async def base_drive_keys(body: DriveBaseKeysRequest) -> dict[str, Any]:
        return await call_rpc("drive_base_keys", keys=body.keys)

    @app.post("/api/base/stop")
    async def base_stop() -> dict[str, Any]:
        return await call_rpc("stop_base")

    @app.post("/api/base/speed/{level}")
    async def base_speed(level: int) -> dict[str, Any]:
        return await call_rpc("set_base_speed_level", level=level)

    @app.get("/api/cameras")
    async def list_cameras() -> dict[str, Any]:
        return await call_rpc("list_cameras")

    @app.get("/api/cameras/{camera}/frame.jpg")
    async def camera_frame(camera: str, quality: int = 80) -> Response:
        result = await call_rpc("get_camera_video", camera=camera, jpeg_quality=quality)
        if result.get("status") != "success":
            raise HTTPException(status_code=404, detail=result.get("reason", "capture failed"))
        data = base64.b64decode(result["data_b64"])
        return Response(content=data, media_type="image/jpeg")

    @app.get("/api/cameras/{camera}/stream.mjpg")
    async def camera_stream(camera: str, request: Request, quality: int = 75) -> StreamingResponse:
        async def generate():
            while True:
                if await request.is_disconnected():
                    break
                result = await call_rpc(
                    "get_camera_video",
                    camera=camera,
                    jpeg_quality=quality,
                )
                if result.get("status") != "success":
                    logger.warning("camera %s stream error: %s", camera, result.get("reason"))
                    await asyncio.sleep(0.5)
                    continue
                frame = base64.b64decode(result["data_b64"])
                header = (
                    b"--"
                    + MJPEG_BOUNDARY
                    + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(frame)).encode()
                    + b"\r\n\r\n"
                )
                yield header + frame + b"\r\n"
                await asyncio.sleep(frame_interval)

        return StreamingResponse(
            generate(),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY.decode()}",
        )

    return app
