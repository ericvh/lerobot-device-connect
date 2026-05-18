"""Unit tests for observation serialization."""

from __future__ import annotations

import numpy as np

from lerobot_device_connect.observation_codec import scalar_observation


def test_scalar_observation_filters_arrays():
    obs = {
        "arm_gripper.pos": 1.5,
        "front": np.zeros((480, 640, 3), dtype=np.uint8),
    }
    scalars = scalar_observation(obs)
    assert scalars == {"arm_gripper.pos": 1.5}
    assert "front" not in scalars
