"""Tests for the web teleop FastAPI app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lerobot_device_connect.web_teleop.app import create_app
from lerobot_device_connect.web_teleop.session import DirectRobotSession, DirectSessionConfig

pytest.importorskip("fastapi")


@pytest.fixture
def client() -> TestClient:
    session = DirectRobotSession(DirectSessionConfig(robot_mode="sim"))
    app = create_app(session, fps=5.0)
    with TestClient(app) as test_client:
        yield test_client


def test_index_and_status(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "LeRobot Web Teleop" in home.text

    conn = client.get("/api/connection")
    assert conn.status_code == 200
    assert "direct" in conn.json()["mode"]

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["connected"] is True


def test_arm_and_base_api(client: TestClient) -> None:
    cfg = client.get("/api/arm/config")
    assert cfg.status_code == 200
    assert "arm_gripper" in cfg.json()["joints"]

    drive = client.post("/api/base/drive", json={"direction": "forward"})
    assert drive.status_code == 200
    assert drive.json()["status"] == "success"

    joint = client.post("/api/arm/joint", json={"joint": "gripper", "position": 30.0})
    assert joint.status_code == 200
    assert joint.json()["positions"]["arm_gripper"] == 30.0
