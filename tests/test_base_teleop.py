"""Tests for base velocity teleop helpers."""

from __future__ import annotations

from lerobot_device_connect.base_teleop import (
    base_velocity_for_directions,
    clamp_speed_index,
)


def test_forward_velocity_at_slow_speed():
    action = base_velocity_for_directions({"forward"}, speed_index=0)
    assert action == {"x.vel": 0.1, "y.vel": 0.0, "theta.vel": 0.0}


def test_combined_directions():
    action = base_velocity_for_directions({"forward", "rotate_left"}, speed_index=2)
    assert action["x.vel"] == 0.3
    assert action["theta.vel"] == 90.0


def test_stop_zeros_velocity():
    action = base_velocity_for_directions({"forward", "stop"}, speed_index=1)
    assert action == {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}


def test_clamp_speed_index():
    assert clamp_speed_index(-1) == 0
    assert clamp_speed_index(99) == 2
