"""Tests for arm joint helpers."""

from __future__ import annotations

import pytest

from lerobot_device_connect.arm_control import (
    build_arm_position_action,
    extract_arm_positions,
    normalize_arm_joint,
    parse_arm_position_updates,
)


def test_normalize_arm_joint_accepts_short_and_full_names():
    assert normalize_arm_joint("gripper") == "arm_gripper"
    assert normalize_arm_joint("arm_gripper.pos") == "arm_gripper"
    assert normalize_arm_joint("arm-elbow-flex") == "arm_elbow_flex"
    assert normalize_arm_joint("unknown") is None


def test_build_arm_position_action_zeros_base():
    action = build_arm_position_action({"gripper": 42.0})
    assert action == {
        "arm_gripper.pos": 42.0,
        "x.vel": 0.0,
        "y.vel": 0.0,
        "theta.vel": 0.0,
    }


def test_parse_arm_position_updates_reports_unknown():
    parsed, unknown = parse_arm_position_updates({"gripper": 1.0, "bad": 2.0})
    assert parsed == {"arm_gripper": 1.0}
    assert unknown == ["bad"]


def test_build_arm_position_action_rejects_unknown_joint():
    with pytest.raises(ValueError, match="unknown arm joint"):
        build_arm_position_action({"bad_joint": 1.0})


def test_extract_arm_positions():
    scalars = {"arm_gripper.pos": 10.0, "x.vel": 0.1, "front": "ignored"}
    assert extract_arm_positions(scalars) == {"arm_gripper": 10.0}
