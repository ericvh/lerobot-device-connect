"""Thin adapters from LeRobot :class:`~lerobot.robots.robot.Robot` to async-friendly I/O."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from lerobot_device_connect.config import default_calibration_dir

from lerobot.types import RobotAction, RobotObservation

logger = logging.getLogger(__name__)


@runtime_checkable
class RobotBridge(Protocol):
    """Minimal robot surface used by the Device Connect driver."""

    robot_kind: str
    robot_id: str

    @property
    def is_connected(self) -> bool: ...

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def get_observation(self) -> RobotObservation: ...

    def send_action(self, action: RobotAction) -> RobotAction: ...

    def observation_features(self) -> dict[str, Any]: ...

    def action_features(self) -> dict[str, Any]: ...

    def stop_base(self) -> None: ...


def _feature_schema(features: dict[str, Any]) -> dict[str, str]:
    """Convert LeRobot feature maps to JSON-schema-like type names."""
    schema: dict[str, str] = {}
    for key, ft in features.items():
        if isinstance(ft, tuple):
            schema[key] = f"image{ft}"
        elif ft is float:
            schema[key] = "float"
        elif ft is int:
            schema[key] = "int"
        else:
            schema[key] = str(ft)
    return schema


@dataclass
class LeKiwiLocalBridge:
    """On-robot LeKiwi (Feetech bus + cameras)."""

    port: str = "/dev/ttyACM0"
    robot_id: str = "lekiwi"
    calibration_dir: Path | None = None
    robot_kind: str = "lekiwi"

    def __post_init__(self) -> None:
        from lerobot.robots.lekiwi import LeKiwi, LeKiwiConfig

        calibration_dir = self.calibration_dir or default_calibration_dir(self.robot_id)
        self._robot = LeKiwi(
            LeKiwiConfig(
                port=self.port,
                id=self.robot_id,
                calibration_dir=calibration_dir,
            )
        )

    @property
    def is_connected(self) -> bool:
        return self._robot.is_connected

    def connect(self) -> None:
        logger.info("Connecting local LeKiwi (port=%s id=%s)", self.port, self.robot_id)
        self._robot.connect()

    def disconnect(self) -> None:
        self._robot.disconnect()

    def get_observation(self) -> RobotObservation:
        return self._robot.get_observation()

    def send_action(self, action: RobotAction) -> RobotAction:
        return self._robot.send_action(action)

    def observation_features(self) -> dict[str, Any]:
        return _feature_schema(self._robot.observation_features)

    def action_features(self) -> dict[str, Any]:
        return _feature_schema(self._robot.action_features)

    def stop_base(self) -> None:
        self._robot.stop_base()


@dataclass
class LeKiwiClientBridge:
    """Remote LeKiwi via ZMQ (requires ``lerobot.robots.lekiwi.lekiwi_host`` on the robot)."""

    remote_ip: str
    robot_id: str = "lekiwi"
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556
    robot_kind: str = "lekiwi_client"

    def __post_init__(self) -> None:
        from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig

        self._robot = LeKiwiClient(
            LeKiwiClientConfig(
                remote_ip=self.remote_ip,
                id=self.robot_id,
                port_zmq_cmd=self.port_zmq_cmd,
                port_zmq_observations=self.port_zmq_observations,
            )
        )

    @property
    def is_connected(self) -> bool:
        return self._robot.is_connected

    def connect(self) -> None:
        logger.info(
            "Connecting LeKiwi client (remote=%s id=%s)",
            self.remote_ip,
            self.robot_id,
        )
        self._robot.connect()

    def disconnect(self) -> None:
        self._robot.disconnect()

    def get_observation(self) -> RobotObservation:
        return self._robot.get_observation()

    def send_action(self, action: RobotAction) -> RobotAction:
        return self._robot.send_action(action)

    def observation_features(self) -> dict[str, Any]:
        return _feature_schema(self._robot.observation_features)

    def action_features(self) -> dict[str, Any]:
        return _feature_schema(self._robot.action_features)

    def stop_base(self) -> None:
        self._robot.send_action({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})

    def base_action_from_keyboard(self, pressed_keys: list[str] | set[str]) -> dict[str, float]:
        """Map keyboard keys to base velocity commands (LeKiwi client teleop helper)."""
        return self._robot._from_keyboard_to_base_action(pressed_keys)


@dataclass
class SimLeKiwiBridge:
    """In-process stub for smoke tests without hardware."""

    robot_id: str = "lekiwi-sim"
    robot_kind: str = "lekiwi_sim"
    _connected: bool = False

    _STATE_KEYS: tuple[str, ...] = (
        "arm_shoulder_pan.pos",
        "arm_shoulder_lift.pos",
        "arm_elbow_flex.pos",
        "arm_wrist_flex.pos",
        "arm_wrist_roll.pos",
        "arm_gripper.pos",
        "x.vel",
        "y.vel",
        "theta.vel",
    )

    def __post_init__(self) -> None:
        self._state = {key: 0.0 for key in self._STATE_KEYS}

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def get_observation(self) -> RobotObservation:
        return dict(self._state)

    def send_action(self, action: RobotAction) -> RobotAction:
        for key in self._STATE_KEYS:
            if key in action:
                self._state[key] = float(action[key])
        return dict(self._state)

    def observation_features(self) -> dict[str, Any]:
        return {key: "float" for key in self._STATE_KEYS}

    def action_features(self) -> dict[str, Any]:
        return {key: "float" for key in self._STATE_KEYS}

    def stop_base(self) -> None:
        self._state["x.vel"] = 0.0
        self._state["y.vel"] = 0.0
        self._state["theta.vel"] = 0.0


def build_robot_bridge(
    *,
    mode: str,
    robot_id: str,
    port: str | None = None,
    remote_ip: str | None = None,
    calibration_dir: Path | None = None,
) -> RobotBridge:
    """Factory for supported robot bridge modes."""
    normalized = mode.strip().lower()
    if normalized in {"sim", "simulate", "simulated"}:
        return SimLeKiwiBridge(robot_id=robot_id or "lekiwi-sim")
    if normalized in {"local", "lekiwi", "lekiwi_local", "host"}:
        return LeKiwiLocalBridge(
            port=port or "/dev/ttyACM0",
            robot_id=robot_id,
            calibration_dir=calibration_dir,
        )
    if normalized in {"client", "lekiwi_client", "remote"}:
        if not remote_ip:
            raise ValueError("remote_ip is required for lekiwi client mode")
        return LeKiwiClientBridge(remote_ip=remote_ip, robot_id=robot_id)
    raise ValueError(
        f"unsupported robot mode {mode!r}; use sim, local/lekiwi, or client/lekiwi_client"
    )
