"""Optional teleoperators composed like ``examples/lekiwi/teleoperate.py``."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lerobot_device_connect.robot_bridge import LeKiwiClientBridge, RobotBridge

logger = logging.getLogger(__name__)


@dataclass
class TeleopConfig:
    """Configuration for leader-arm + keyboard teleop."""

    leader_port: str | None = None
    leader_id: str = "leader_arm"
    keyboard_id: str = "keyboard"
    enable_keyboard: bool = True


class TeleopComposer:
    """Merges leader arm joints and keyboard base commands into one robot action."""

    def __init__(self, config: TeleopConfig) -> None:
        self.config = config
        self._leader = None
        self._keyboard = None
        self._connected = False

    @property
    def is_configured(self) -> bool:
        return bool(self.config.leader_port or self.config.enable_keyboard)

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self.config.leader_port:
            from lerobot.teleoperators.so_leader import SO100Leader, SO100LeaderConfig

            self._leader = SO100Leader(
                SO100LeaderConfig(port=self.config.leader_port, id=self.config.leader_id)
            )
            self._leader.connect()
            logger.info("Leader arm connected on %s", self.config.leader_port)

        if self.config.enable_keyboard:
            from lerobot.teleoperators.keyboard.teleop_keyboard import (
                KeyboardTeleop,
                KeyboardTeleopConfig,
            )

            self._keyboard = KeyboardTeleop(KeyboardTeleopConfig(id=self.config.keyboard_id))
            self._keyboard.connect()
            logger.info("Keyboard teleop connected")

        self._connected = True

    def disconnect(self) -> None:
        if self._leader is not None:
            self._leader.disconnect()
        if self._keyboard is not None:
            self._keyboard.disconnect()
        self._connected = False

    def compose_action(self, robot: RobotBridge) -> dict[str, Any]:
        """Build a combined action dict for *robot* (LeKiwi client base mapping)."""
        action: dict[str, Any] = {}

        if self._leader is not None:
            arm_action = self._leader.get_action()
            action.update({f"arm_{k}": v for k, v in arm_action.items()})

        if self._keyboard is not None and isinstance(robot, LeKiwiClientBridge):
            keyboard_keys = self._keyboard.get_action()
            base_action = robot.base_action_from_keyboard(keyboard_keys)
            if base_action:
                action.update(base_action)

        return action
