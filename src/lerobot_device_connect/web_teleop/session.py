"""Robot sessions for the web teleop UI (Device Connect or in-process)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from lerobot_device_connect.config import DriverConfig, default_calibration_dir, default_robot_id
from lerobot_device_connect.device_connect import LeRobotDeviceDriver
from lerobot_device_connect.device_connect_invoker import (
    DeviceConnectInvoker,
    DeviceConnectRpcError,
    InvokerConfig,
)
from lerobot_device_connect.robot_bridge import build_robot_bridge

logger = logging.getLogger(__name__)


@runtime_checkable
class RobotSession(Protocol):
    """Common surface for direct and Device Connect backends."""

    @property
    def mode_label(self) -> str: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def rpc(self, method: str, **params: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DirectSessionConfig:
    robot_mode: str = "sim"
    robot_id: str = ""
    robot_port: str = "/dev/ttyACM0"
    calibration_dir: str | None = None
    remote_ip: str | None = None


class DirectRobotSession:
    """Runs ``LeRobotDeviceDriver`` in-process (local/sim/client bridge)."""

    def __init__(self, config: DirectSessionConfig) -> None:
        self._config = config
        self._driver: LeRobotDeviceDriver | None = None

    @property
    def mode_label(self) -> str:
        return f"direct ({self._config.robot_mode})"

    @property
    def driver(self) -> LeRobotDeviceDriver:
        if self._driver is None:
            raise RuntimeError("robot session not connected")
        return self._driver

    async def connect(self) -> None:
        if self._driver is not None:
            return
        robot_id = self._config.robot_id or default_robot_id()
        calibration_dir = self._config.calibration_dir
        if calibration_dir is None:
            auto = default_calibration_dir(robot_id)
            calibration_dir = str(auto) if auto else None
        robot = build_robot_bridge(
            mode=self._config.robot_mode,
            robot_id=robot_id,
            port=self._config.robot_port,
            remote_ip=self._config.remote_ip,
            calibration_dir=Path(calibration_dir) if calibration_dir else None,
        )
        self._driver = LeRobotDeviceDriver(robot, state_publish_hz=5.0)
        await self._driver.connect()
        logger.info("Web teleop direct session (mode=%s id=%s)", self._config.robot_mode, robot_id)

    async def disconnect(self) -> None:
        if self._driver is None:
            return
        await self._driver.disconnect()
        self._driver = None

    async def rpc(self, method: str, **params: Any) -> dict[str, Any]:
        handler = getattr(self.driver, method)
        return await handler(**params)


class DeviceConnectRobotSession:
    """Invokes RPCs on a remote ``lerobot-device-connect`` device over the mesh."""

    def __init__(self, invoker: DeviceConnectInvoker) -> None:
        self._invoker = invoker

    @property
    def mode_label(self) -> str:
        return f"device-connect ({self._invoker.target_device_id}@{self._invoker.tenant})"

    async def connect(self) -> None:
        await self._invoker.connect()

    async def disconnect(self) -> None:
        await self._invoker.disconnect()

    async def rpc(self, method: str, **params: Any) -> dict[str, Any]:
        try:
            return await self._invoker.invoke(method, params)
        except DeviceConnectRpcError:
            raise


def build_session(
    *,
    use_direct: bool,
    driver_config: DriverConfig,
    direct_config: DirectSessionConfig,
    target_device_id: str,
) -> RobotSession:
    if use_direct:
        return DirectRobotSession(direct_config)
    invoker = DeviceConnectInvoker(
        InvokerConfig.from_driver_config(driver_config, target_device_id=target_device_id)
    )
    return DeviceConnectRobotSession(invoker)
