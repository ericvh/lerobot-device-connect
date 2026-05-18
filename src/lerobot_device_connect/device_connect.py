"""Device Connect driver wrapping a LeRobot robot bridge."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from device_connect_edge.drivers import DeviceDriver, emit, periodic, rpc
from device_connect_edge.types import DeviceIdentity, DeviceStatus

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
