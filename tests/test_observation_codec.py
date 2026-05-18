"""Unit tests for observation serialization."""

from __future__ import annotations

import numpy as np

from lerobot_device_connect.observation_codec import scalar_observation, scalars_changed


def test_scalar_observation_filters_arrays():
    obs = {
        "arm_gripper.pos": 1.5,
        "front": np.zeros((480, 640, 3), dtype=np.uint8),
    }
    scalars = scalar_observation(obs)
    assert scalars == {"arm_gripper.pos": 1.5}
    assert "front" not in scalars


def test_scalars_changed_detects_value_and_key_differences():
    before = {"arm_gripper.pos": 1.0, "x.vel": 0.0}
    assert not scalars_changed(before, dict(before))
    assert scalars_changed(before, {"arm_gripper.pos": 1.0002, "x.vel": 0.0})
    assert scalars_changed(before, {"arm_gripper.pos": 1.0, "x.vel": 0.01})
    assert scalars_changed(before, {"arm_gripper.pos": 1.0})


def test_scalars_changed_treats_empty_as_changed():
    assert scalars_changed({}, {"arm_gripper.pos": 0.0})
