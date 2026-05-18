"""CLI for the LeRobot browser teleop test server."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from lerobot_device_connect.config import DriverConfig, default_calibration_dir, default_robot_id
from lerobot_device_connect.logging_setup import configure_driver_logging
from lerobot_device_connect.runtime_launcher import gather_cli_run_params
from lerobot_device_connect.web_teleop.app import create_app
from lerobot_device_connect.web_teleop.session import DirectSessionConfig, build_session

configure_driver_logging()
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Web UI for LeKiwi teleop (cameras, base, arm). "
            "Default: invoke a remote lerobot-device-connect device over Device Connect."
        ),
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address.")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port.")
    parser.add_argument("--fps", type=float, default=8.0, help="Target camera stream FPS.")
    parser.add_argument(
        "--target-device-id",
        default=None,
        help="Device Connect id of the robot (lerobot-device-connect --device-id).",
    )
    parser.add_argument("--tenant", default=None)
    parser.add_argument("--portal", action="store_true", help="Use portal NATS + credentials.")
    parser.add_argument("--portal-credentials", default=None)
    parser.add_argument("--portal-credentials-glob", default=None)
    parser.add_argument("--portal-credentials-dir", default=None)
    parser.add_argument("--messaging-url", action="append", default=None)
    parser.add_argument("--messaging-backend", default=None)
    parser.add_argument("--nats-credentials-file", default=None)
    parser.add_argument("--allow-insecure", action="store_true")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Run driver in-process instead of Device Connect (local testing).",
    )
    parser.add_argument("--robot-mode", default=None, choices=["sim", "local", "client"])
    parser.add_argument("--sim", action="store_true", help="Direct mode: simulated robot.")
    parser.add_argument("--robot-id", default=None)
    parser.add_argument("--calibration-dir", default=None)
    parser.add_argument("--robot-port", default=None)
    parser.add_argument("--remote-ip", default=None)
    return parser


def _resolve_target_device_id(args: argparse.Namespace, driver_config: DriverConfig) -> str:
    target = (
        args.target_device_id
        or os.environ.get("LEROBOT_TARGET_DEVICE_ID")
        or os.environ.get("LEROBOT_DEVICE_TARGET")
    )
    if target:
        return target
    if driver_config.portal and driver_config.device_id:
        # Portal creds often name the robot device; usable when ids match.
        return driver_config.device_id
    return driver_config.device_id


def main() -> None:
    args = build_parser().parse_args()

    if args.direct:
        env = DriverConfig.from_env()
        robot_mode = "sim" if args.sim else (args.robot_mode or env.robot_mode)
        robot_id = args.robot_id or env.robot_id or default_robot_id()
        calibration_dir = args.calibration_dir or env.calibration_dir
        if calibration_dir is None:
            auto = default_calibration_dir(robot_id)
            calibration_dir = str(auto) if auto else None
        direct_config = DirectSessionConfig(
            robot_mode=robot_mode,
            robot_id=robot_id,
            robot_port=args.robot_port or env.robot_port,
            calibration_dir=calibration_dir,
            remote_ip=args.remote_ip or env.remote_ip,
        )
        driver_config = env
        target_device_id = ""
    else:
        dc_args = argparse.Namespace(
            device_id=args.target_device_id,
            tenant=args.tenant,
            robot_mode=None,
            sim=False,
            robot_id=None,
            calibration_dir=None,
            robot_port=None,
            remote_ip=None,
            leader_port=None,
            keyboard_teleop=False,
            state_hz=None,
            messaging_backend=args.messaging_backend,
            messaging_url=args.messaging_url,
            nats_credentials_file=args.nats_credentials_file,
            portal=args.portal,
            portal_credentials=args.portal_credentials,
            portal_credentials_glob=args.portal_credentials_glob,
            portal_credentials_dir=args.portal_credentials_dir,
            allow_insecure=args.allow_insecure,
        )
        params = gather_cli_run_params(dc_args)
        driver_config = params.driver_config
        direct_config = DirectSessionConfig()
        target_device_id = _resolve_target_device_id(args, driver_config)
        if not target_device_id:
            print(
                "Device Connect mode requires --target-device-id (robot's Device Connect id).\n"
                "Example: lerobot-web-teleop --portal --target-device-id my-lekiwi\n"
                "The robot must be running: lerobot-device-connect --device-id my-lekiwi ...",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if not driver_config.nats_credentials_file and not driver_config.allow_insecure:
            print(
                "Device Connect mode requires mesh credentials.\n"
                "Use --portal / --portal-credentials, --nats-credentials-file, or --allow-insecure.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    session = build_session(
        use_direct=args.direct,
        driver_config=driver_config,
        direct_config=direct_config,
        target_device_id=target_device_id,
    )
    app = create_app(session, fps=args.fps)

    logger.warning(
        "Web teleop at http://%s:%s [%s] — no authentication; lab use only.",
        args.host,
        args.port,
        session.mode_label,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
