"""CLI runner for the LeRobot Device Connect driver."""

from __future__ import annotations

import argparse
import asyncio

from lerobot_device_connect.logging_setup import configure_driver_logging
from lerobot_device_connect.runtime_launcher import gather_cli_run_params, run_device_connect

configure_driver_logging()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", default=None)
    parser.add_argument("--tenant", default=None)
    parser.add_argument(
        "--robot-mode",
        default=None,
        choices=["sim", "local", "client", "lekiwi", "lekiwi_client"],
        help="Robot bridge: sim, local (on-robot LeKiwi), or client (ZMQ to lekiwi_host).",
    )
    parser.add_argument("--sim", action="store_true", help="Use simulated LeKiwi (no hardware).")
    parser.add_argument(
        "--robot-id",
        default=None,
        help="LeRobot robot id (default: hostname, e.g. dum-e for ~/dum-e.json calibration).",
    )
    parser.add_argument(
        "--calibration-dir",
        default=None,
        help="Directory containing {robot-id}.json (default: ~ when ~/{{robot-id}}.json exists).",
    )
    parser.add_argument("--robot-port", default=None, help="Feetech bus port for local LeKiwi.")
    parser.add_argument("--remote-ip", default=None, help="Robot IP for LeKiwi client mode.")
    parser.add_argument(
        "--leader-port",
        default=None,
        help="SO100 leader arm serial port; enables teleop_step when set.",
    )
    parser.add_argument(
        "--keyboard-teleop",
        action="store_true",
        help="Enable keyboard base teleop (LeKiwi client mode).",
    )
    parser.add_argument("--state-hz", type=float, default=None, help="State publish rate.")
    parser.add_argument("--messaging-backend", default=None)
    parser.add_argument("--messaging-url", action="append", default=None)
    parser.add_argument("--nats-credentials-file", default=None)
    parser.add_argument("--portal", action="store_true")
    parser.add_argument("--portal-credentials", default=None)
    parser.add_argument("--portal-credentials-glob", default=None)
    parser.add_argument("--portal-credentials-dir", default=None)
    parser.add_argument("--allow-insecure", action="store_true")
    return parser


async def _run_cli(args: argparse.Namespace) -> None:
    params = gather_cli_run_params(args)
    await run_device_connect(params)


def main() -> None:
    asyncio.run(_run_cli(build_parser().parse_args()))


if __name__ == "__main__":
    main()
