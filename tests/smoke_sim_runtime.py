"""Smoke-test the simulated LeKiwi bridge through Device Connect shapes."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from device_connect_edge import DeviceRuntime

from lerobot_device_connect.device_connect import LeRobotDeviceDriver
from lerobot_device_connect.robot_bridge import SimLeKiwiBridge

REQUIRED_FUNCTIONS = {
    "get_features",
    "get_status",
    "get_observation",
    "get_observation_with_cameras",
    "send_action",
    "stop_base",
    "teleop_step",
}

REQUIRED_EVENTS = {"state_update", "emergency_stop"}


async def main() -> None:
    robot = SimLeKiwiBridge()
    driver = LeRobotDeviceDriver(robot)
    runtime = DeviceRuntime(
        driver=driver,
        device_id="lekiwi-sim-smoke",
        tenant="smoke",
        allow_insecure=True,
    )

    function_names = {func.name for func in runtime.capabilities.functions}
    event_names = {event.name for event in runtime.capabilities.events}
    missing_functions = sorted(REQUIRED_FUNCTIONS - function_names)
    missing_events = sorted(REQUIRED_EVENTS - event_names)
    if missing_functions or missing_events:
        raise AssertionError(
            {"missing_functions": missing_functions, "missing_events": missing_events}
        )

    await driver.connect()
    features = await driver.invoke("get_features")
    status = await driver.invoke("get_status")
    await driver.invoke("send_action", action={"arm_gripper.pos": 42.0})
    obs = await driver.invoke("get_observation")
    await driver.invoke("stop_base")
    teleop = await driver.invoke("teleop_step")
    await driver.disconnect()

    if features["robot_kind"] != "lekiwi_sim":
        raise AssertionError("unexpected robot_kind")
    if not status["connected"]:
        raise AssertionError("sim robot should be connected")
    if obs["observation"].get("arm_gripper.pos") != 42.0:
        raise AssertionError("send_action did not update simulated state")
    if teleop["status"] != "error":
        raise AssertionError("teleop_step without teleop should return error")

    print(
        json.dumps(
            {
                "status": "ok",
                "device_id": runtime.device_id,
                "functions": sorted(function_names),
                "events": sorted(event_names),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
