"""Tests for robot bridge helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lerobot_device_connect.robot_bridge import _merge_arm_hold_positions


def test_merge_arm_hold_positions_adds_present_arm_pose():
    robot = MagicMock()
    robot.arm_motors = ["arm_gripper"]
    robot.bus.sync_read.return_value = {"arm_gripper": 12.5}

    merged = _merge_arm_hold_positions(
        robot,
        {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 30.0},
    )

    assert merged == {
        "arm_gripper.pos": 12.5,
        "x.vel": 0.0,
        "y.vel": 0.0,
        "theta.vel": 30.0,
    }
    robot.bus.sync_read.assert_called_once_with("Present_Position", ["arm_gripper"])


def test_merge_arm_hold_positions_passthrough_when_arm_in_action():
    robot = MagicMock()
    action = {"arm_gripper.pos": 1.0, "x.vel": 0.1, "y.vel": 0.0, "theta.vel": 0.0}
    assert _merge_arm_hold_positions(robot, action) == action
    robot.bus.sync_read.assert_not_called()


def test_empty_motor_map_raises_stop_iteration():
    """Document the LeRobot footgun that base-only actions trigger."""
    with pytest.raises(StopIteration):
        next(iter([]))
