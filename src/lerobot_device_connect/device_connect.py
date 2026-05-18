"""Device Connect driver wrapping a LeRobot robot bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from device_connect_edge.drivers import DeviceDriver, emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

from lerobot_device_connect.base_teleop import (
    BASE_DIRECTIONS,
    DEFAULT_SPEED_LEVELS,
    base_teleop_config,
    base_velocity_for_directions,
    clamp_speed_index,
)
from lerobot_device_connect.camera_media import (
    capture_alsa_audio,
    encode_all_cameras_from_observation,
    encode_camera_from_observation,
    resolve_camera_audio_devices,
)
from lerobot_device_connect.observation_codec import (
    observation_with_cameras,
    scalar_observation,
    scalars_changed,
)
from lerobot_device_connect.robot_bridge import RobotBridge
from lerobot_device_connect.teleop import TeleopComposer, TeleopConfig

logger = logging.getLogger(__name__)


class LeRobotDeviceDriver(DeviceDriver):
    """Self-hosted Device Connect driver for LeRobot robots (LeKiwi first)."""

    device_type = "lerobot_robot"

    def __init__(
        self,
        robot: RobotBridge,
        *,
        teleop: TeleopComposer | None = None,
        state_publish_hz: float = 10.0,
    ) -> None:
        super().__init__()
        self.robot = robot
        self.teleop = teleop
        self.state_publish_hz = state_publish_hz
        self._last_scalars: dict[str, float | int | str] = {}
        self._last_emitted_scalars: dict[str, float | int | str] = {}
        self._hw_connected = False
        self._base_speed_index = 0
        self._audio_device_overrides = _load_audio_device_overrides()

    @property
    def identity(self) -> DeviceIdentity:
        model = f"{self.robot.robot_kind} ({self.robot.robot_id})"
        return DeviceIdentity(
            device_type=self.device_type,
            manufacturer="Hugging Face",
            model=model,
            description="LeRobot robot exposed via Device Connect (LeKiwi teleop/observation)",
        )

    @property
    def status(self) -> DeviceStatus:
        availability = "idle"
        if not self._hw_connected:
            availability = "offline"
        return DeviceStatus(ts=datetime.now(UTC), availability=availability)

    async def connect(self) -> None:
        await asyncio.to_thread(self.robot.connect)
        if self.teleop is not None and self.teleop.is_configured:
            await asyncio.to_thread(self.teleop.connect)
        self._hw_connected = True
        logger.info(
            "LeRobot driver connected (kind=%s id=%s teleop=%s)",
            self.robot.robot_kind,
            self.robot.robot_id,
            self.teleop is not None and self.teleop.is_configured,
        )

    async def disconnect(self) -> None:
        if self.teleop is not None and self.teleop.is_connected:
            await asyncio.to_thread(self.teleop.disconnect)
        await asyncio.to_thread(self.robot.disconnect)
        self._hw_connected = False
        self._last_emitted_scalars = {}
        logger.info("LeRobot driver disconnected")

    @rpc()
    async def get_features(self) -> dict[str, Any]:
        """Return observation and action feature schemas."""
        return {
            "robot_kind": self.robot.robot_kind,
            "robot_id": self.robot.robot_id,
            "observation_features": self.robot.observation_features(),
            "action_features": self.robot.action_features(),
            "teleop_configured": self.teleop is not None and self.teleop.is_configured,
        }

    @rpc()
    async def get_status(self) -> dict[str, Any]:
        """Return connection and last known scalar state."""
        return {
            "connected": self.robot.is_connected,
            "robot_kind": self.robot.robot_kind,
            "robot_id": self.robot.robot_id,
            "last_scalars": self._last_scalars,
            "teleop_connected": self.teleop.is_connected if self.teleop else False,
        }

    @rpc()
    async def get_observation(self) -> dict[str, Any]:
        """Return the latest scalar observation (no camera frames)."""
        obs = await asyncio.to_thread(self.robot.get_observation)
        scalars = scalar_observation(obs)
        self._last_scalars = scalars
        return {"status": "success", "observation": scalars}

    @rpc()
    async def get_observation_with_cameras(self, jpeg_quality: int = 85) -> dict[str, Any]:
        """Return scalar state and JPEG-encoded camera frames.

        Args:
            jpeg_quality: JPEG quality for camera encoding (1–100).
        """
        obs = await asyncio.to_thread(self.robot.get_observation)
        payload = observation_with_cameras(obs, jpeg_quality=jpeg_quality)
        self._last_scalars = payload.get("scalars", {})
        return {"status": "success", **payload}

    @rpc()
    async def send_action(self, action: dict[str, float]) -> dict[str, Any]:
        """Send a motor-space action to the robot.

        Args:
            action: Keys matching LeRobot action features (e.g. arm joint positions, base velocities).
        """
        sent = await asyncio.to_thread(self.robot.send_action, action)
        scalars = scalar_observation(sent) if isinstance(sent, dict) else {}
        return {"status": "success", "action_sent": scalars}

    @rpc()
    async def stop_base(self) -> dict[str, str]:
        """Stop the mobile base (LeKiwi omniwheel velocities to zero)."""
        await asyncio.to_thread(self.robot.stop_base)
        return {"status": "success"}

    @rpc()
    async def get_base_teleop_config(self) -> dict[str, Any]:
        """Return base drive directions and speed levels (keyboard teleop semantics)."""
        return {
            "status": "success",
            **base_teleop_config(speed_index=self._base_speed_index),
        }

    @rpc()
    async def set_base_speed_level(self, level: int) -> dict[str, Any]:
        """Set base speed tier (0=slow, 1=medium, 2=fast)."""
        self._base_speed_index = clamp_speed_index(level, num_levels=len(DEFAULT_SPEED_LEVELS))
        return {
            "status": "success",
            "speed_index": self._base_speed_index,
            "speed": dict(DEFAULT_SPEED_LEVELS[self._base_speed_index]),
        }

    @rpc()
    async def base_speed_up(self) -> dict[str, Any]:
        """Increase base speed tier (capped at fast)."""
        return await self.set_base_speed_level(self._base_speed_index + 1)

    @rpc()
    async def base_speed_down(self) -> dict[str, Any]:
        """Decrease base speed tier (capped at slow)."""
        return await self.set_base_speed_level(self._base_speed_index - 1)

    @rpc()
    async def set_base_velocity(
        self,
        x_vel: float = 0.0,
        y_vel: float = 0.0,
        theta_vel: float = 0.0,
    ) -> dict[str, Any]:
        """Set omniwheel body velocities directly (m/s, m/s, deg/s)."""
        sent = await asyncio.to_thread(
            self._send_base_velocity,
            float(x_vel),
            float(y_vel),
            float(theta_vel),
        )
        return {"status": "success", "action_sent": scalar_observation(sent)}

    @rpc()
    async def drive_base(self, direction: str) -> dict[str, Any]:
        """Drive base in one teleop direction (forward, backward, left, right, rotate_*, stop)."""
        normalized = direction.strip().lower()
        if normalized not in BASE_DIRECTIONS:
            return {
                "status": "error",
                "reason": f"invalid direction {direction!r}; use one of {sorted(BASE_DIRECTIONS)}",
            }
        if normalized == "stop":
            await asyncio.to_thread(self.robot.stop_base)
            return {"status": "success", "action_sent": {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}}
        action = base_velocity_for_directions(
            {normalized},
            speed_index=self._base_speed_index,
        )
        sent = await asyncio.to_thread(
            self._send_base_velocity,
            action["x.vel"],
            action["y.vel"],
            action["theta.vel"],
        )
        return {
            "status": "success",
            "direction": normalized,
            "speed_index": self._base_speed_index,
            "action_sent": scalar_observation(sent),
        }

    @rpc()
    async def drive_base_keys(self, keys: list[str]) -> dict[str, Any]:
        """Drive base using multiple teleop directions at once (e.g. forward + left)."""
        directions = {key.strip().lower() for key in keys if key.strip()}
        unknown = directions - BASE_DIRECTIONS
        if unknown:
            return {
                "status": "error",
                "reason": f"invalid directions {sorted(unknown)}; use {sorted(BASE_DIRECTIONS)}",
            }
        if "stop" in directions or not directions:
            await asyncio.to_thread(self.robot.stop_base)
            return {"status": "success", "action_sent": {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}}
        action = base_velocity_for_directions(directions, speed_index=self._base_speed_index)
        sent = await asyncio.to_thread(
            self._send_base_velocity,
            action["x.vel"],
            action["y.vel"],
            action["theta.vel"],
        )
        return {
            "status": "success",
            "directions": sorted(directions),
            "speed_index": self._base_speed_index,
            "action_sent": scalar_observation(sent),
        }

    @rpc()
    async def list_cameras(self) -> dict[str, Any]:
        """List camera names and V4L2 device paths when available."""
        names = self.robot.list_cameras()
        paths = self.robot.camera_video_paths()
        audio = resolve_camera_audio_devices(paths, overrides=self._audio_device_overrides)
        return {
            "status": "success",
            "cameras": names,
            "video_paths": {name: str(paths[name]) for name in names if name in paths},
            "audio_devices": {name: audio.get(name) for name in names},
        }

    @rpc()
    async def get_camera_video(self, camera: str, jpeg_quality: int = 85) -> dict[str, Any]:
        """Return a single JPEG-encoded frame from *camera* (``front`` or ``wrist``)."""
        obs = await asyncio.to_thread(self.robot.get_observation)
        return encode_camera_from_observation(obs, camera, jpeg_quality=jpeg_quality)

    @rpc()
    async def get_cameras_video(self, jpeg_quality: int = 85) -> dict[str, Any]:
        """Return JPEG-encoded frames from all configured cameras."""
        obs = await asyncio.to_thread(self.robot.get_observation)
        return encode_all_cameras_from_observation(
            obs,
            camera_names=self.robot.list_cameras(),
            jpeg_quality=jpeg_quality,
        )

    @rpc()
    async def get_camera_audio(
        self,
        camera: str,
        duration_ms: int = 500,
        sample_rate: int = 16000,
    ) -> dict[str, Any]:
        """Capture a short WAV clip from the microphone paired with *camera*."""
        paths = self.robot.camera_video_paths()
        if camera not in paths:
            return {"status": "error", "reason": f"unknown camera {camera!r}"}
        audio_devices = resolve_camera_audio_devices(
            paths,
            overrides=self._audio_device_overrides,
        )
        alsa_device = audio_devices.get(camera)
        if not alsa_device:
            return {
                "status": "error",
                "reason": (
                    f"no ALSA device for camera {camera!r}; set LEROBOT_CAMERA_AUDIO_ALSA "
                    'e.g. {"front":"hw:2,0","wrist":"hw:3,0"}'
                ),
            }
        result = await asyncio.to_thread(
            capture_alsa_audio,
            alsa_device,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
        )
        if result.get("status") == "success":
            result["camera"] = camera
        return result

    @rpc()
    async def get_cameras_audio(
        self,
        duration_ms: int = 500,
        sample_rate: int = 16000,
    ) -> dict[str, Any]:
        """Capture short WAV clips from all camera-associated microphones."""
        paths = self.robot.camera_video_paths()
        audio_devices = resolve_camera_audio_devices(
            paths,
            overrides=self._audio_device_overrides,
        )
        audio: dict[str, Any] = {}
        errors: list[str] = []
        for camera in self.robot.list_cameras():
            alsa_device = audio_devices.get(camera)
            if not alsa_device:
                errors.append(f"{camera}: no ALSA device")
                continue
            result = await asyncio.to_thread(
                capture_alsa_audio,
                alsa_device,
                duration_ms=duration_ms,
                sample_rate=sample_rate,
            )
            if result.get("status") == "success":
                audio[camera] = {k: v for k, v in result.items() if k != "status"}
            else:
                errors.append(f"{camera}: {result.get('reason', 'capture failed')}")
        payload: dict[str, Any] = {"status": "success", "audio": audio}
        if errors:
            payload["errors"] = errors
        return payload

    @rpc()
    async def teleop_step(self) -> dict[str, Any]:
        """Run one teleop cycle: observe, compose leader/keyboard action, send.

        Requires teleop to be configured (leader port and/or keyboard).
        """
        if self.teleop is None or not self.teleop.is_configured:
            return {"status": "error", "reason": "teleop not configured"}
        if not self.teleop.is_connected:
            return {"status": "error", "reason": "teleop not connected"}

        observation = await asyncio.to_thread(self.robot.get_observation)
        action = await asyncio.to_thread(self.teleop.compose_action, self.robot)
        if not action:
            return {
                "status": "success",
                "observation": scalar_observation(observation),
                "action_sent": {},
                "note": "no teleop input",
            }
        sent = await asyncio.to_thread(self.robot.send_action, action)
        scalars = scalar_observation(observation)
        self._last_scalars = scalars
        return {
            "status": "success",
            "observation": scalars,
            "action_sent": scalar_observation(sent) if isinstance(sent, dict) else action,
        }

    @periodic(interval=0.1, wait_for_completion=True)
    async def _publish_state(self) -> None:
        """Poll scalar state at ~10 Hz; emit only when values change."""
        if not self._hw_connected or not self.robot.is_connected:
            return
        obs = await asyncio.to_thread(self.robot.get_observation)
        scalars = scalar_observation(obs)
        self._last_scalars = scalars
        if not scalars_changed(self._last_emitted_scalars, scalars):
            return
        self._last_emitted_scalars = dict(scalars)
        await self.state_update(**scalars)

    @emit()
    async def state_update(self, **joints: float):
        """Scalar joint/base state update (emitted on change only)."""
        pass

    @emit()
    async def emergency_stop(self, reason: str = ""):
        """Emitted when motion is halted for safety."""
        pass

    def _send_base_velocity(self, x_vel: float, y_vel: float, theta_vel: float) -> dict[str, float]:
        """Thread-safe base motion (holds arm pose on local LeKiwi)."""
        send_base = getattr(self.robot, "send_base_velocity", None)
        if callable(send_base):
            return send_base(x_vel, y_vel, theta_vel)
        return self.robot.send_action(
            {"x.vel": x_vel, "y.vel": y_vel, "theta.vel": theta_vel},
        )


def _load_audio_device_overrides() -> dict[str, str]:
    raw = os.environ.get("LEROBOT_CAMERA_AUDIO_ALSA", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid LEROBOT_CAMERA_AUDIO_ALSA (not JSON): %s", raw)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("Ignoring LEROBOT_CAMERA_AUDIO_ALSA: expected JSON object")
        return {}
    return {str(k): str(v) for k, v in parsed.items()}
