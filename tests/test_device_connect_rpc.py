"""Tests for extended Device Connect RPC handlers."""

from __future__ import annotations

import numpy as np
import pytest

from lerobot_device_connect.device_connect import LeRobotDeviceDriver
from lerobot_device_connect.robot_bridge import SimLeKiwiBridge


@pytest.fixture
def driver() -> LeRobotDeviceDriver:
    return LeRobotDeviceDriver(SimLeKiwiBridge())


@pytest.mark.asyncio
async def test_drive_base_forward(driver: LeRobotDeviceDriver) -> None:
    await driver.connect()
    result = await driver.drive_base("forward")
    assert result["status"] == "success"
    assert result["action_sent"]["x.vel"] == 0.1
    await driver.disconnect()


@pytest.mark.asyncio
async def test_set_base_velocity(driver: LeRobotDeviceDriver) -> None:
    await driver.connect()
    result = await driver.set_base_velocity(x_vel=0.05, y_vel=-0.02, theta_vel=10.0)
    assert result["status"] == "success"
    assert result["action_sent"]["x.vel"] == 0.05
    await driver.disconnect()


@pytest.mark.asyncio
async def test_list_cameras_sim_empty(driver: LeRobotDeviceDriver) -> None:
    await driver.connect()
    result = await driver.list_cameras()
    assert result["status"] == "success"
    assert result["cameras"] == []
    await driver.disconnect()


class _CameraStubBridge(SimLeKiwiBridge):
    robot_kind = "lekiwi_sim_cam"

    def list_cameras(self) -> list[str]:
        return ["front", "wrist"]

    def camera_video_paths(self) -> dict[str, str | int]:
        return {"front": "/dev/video0", "wrist": "/dev/video2"}

    def get_observation(self):
        return {
            **super().get_observation(),
            "front": np.zeros((480, 640, 3), dtype=np.uint8),
            "wrist": np.zeros((640, 480, 3), dtype=np.uint8),
        }


@pytest.mark.asyncio
async def test_get_camera_video() -> None:
    driver = LeRobotDeviceDriver(_CameraStubBridge())
    await driver.connect()
    result = await driver.get_camera_video("front", jpeg_quality=80)
    assert result["status"] == "success"
    assert result["encoding"] == "jpeg"
    assert result["data_b64"]
    await driver.disconnect()
