"""Shared async startup for the LeRobot Device Connect CLI."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from argparse import Namespace
from dataclasses import dataclass

from device_connect_edge import DeviceRuntime

from pathlib import Path

from lerobot_device_connect.config import (
    DriverConfig,
    PortalCredentials,
    apply_portal_config,
    default_calibration_dir,
    default_robot_id,
    load_portal_credentials,
    resolve_portal_credentials_file,
)
from lerobot_device_connect.device_connect import LeRobotDeviceDriver
from lerobot_device_connect.logging_setup import configure_driver_logging
from lerobot_device_connect.robot_bridge import build_robot_bridge
from lerobot_device_connect.teleop import TeleopComposer, TeleopConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceConnectRunParams:
    driver_config: DriverConfig
    portal_credentials: PortalCredentials | None


def log_run_config(params: DeviceConnectRunParams) -> None:
    cfg = params.driver_config
    creds = cfg.nats_credentials_file or "(none)"
    urls = ", ".join(cfg.messaging_urls) if cfg.messaging_urls else "(default)"
    logger.info("=== LeRobot Device Connect driver ===")
    logger.info(
        "device_id=%s tenant=%s portal=%s robot_mode=%s",
        cfg.device_id,
        cfg.tenant,
        cfg.portal,
        cfg.robot_mode,
    )
    calibration = cfg.calibration_dir or default_calibration_dir(cfg.robot_id)
    calibration_path = (
        Path(calibration) / f"{cfg.robot_id}.json"
        if calibration
        else f"(lerobot default, id={cfg.robot_id})"
    )
    logger.info(
        "robot_id=%s port=%s calibration=%s remote_ip=%s leader_port=%s keyboard=%s",
        cfg.robot_id,
        cfg.robot_port,
        calibration_path,
        cfg.remote_ip or "(n/a)",
        cfg.leader_port or "(none)",
        cfg.enable_keyboard_teleop,
    )
    logger.info(
        "messaging backend=%s urls=%s credentials=%s",
        cfg.messaging_backend or "(default)",
        urls,
        creds,
    )


def gather_cli_run_params(args: Namespace) -> DeviceConnectRunParams:
    env = DriverConfig.from_env()
    portal = args.portal or env.portal
    messaging_urls = tuple(args.messaging_url) if args.messaging_url else env.messaging_urls
    credentials_file = resolve_portal_credentials_file(
        explicit_path=args.portal_credentials or args.nats_credentials_file or env.nats_credentials_file,
        portal=portal,
        pattern=args.portal_credentials_glob or env.portal_credentials_glob,
        search_dir=args.portal_credentials_dir or env.portal_credentials_dir,
    )
    if portal and not credentials_file:
        print(
            "Portal mode requires credentials. Provide --portal-credentials, "
            "--nats-credentials-file, NATS_CREDENTIALS_FILE, or a matching file under "
            f"{args.portal_credentials_dir or env.portal_credentials_dir}.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    portal_credentials = load_portal_credentials(credentials_file) if credentials_file else None

    robot_mode = args.robot_mode or env.robot_mode
    if args.sim:
        robot_mode = "sim"

    robot_id = args.robot_id or env.robot_id or default_robot_id()
    calibration_dir = args.calibration_dir or env.calibration_dir
    if calibration_dir is None:
        auto_dir = default_calibration_dir(robot_id)
        calibration_dir = str(auto_dir) if auto_dir else None

    config = DriverConfig(
        device_id=args.device_id or env.device_id,
        tenant=args.tenant or env.tenant,
        robot_mode=robot_mode,
        robot_id=robot_id,
        robot_port=args.robot_port or env.robot_port,
        calibration_dir=calibration_dir,
        remote_ip=args.remote_ip or env.remote_ip,
        leader_port=args.leader_port or env.leader_port,
        enable_keyboard_teleop=args.keyboard_teleop or env.enable_keyboard_teleop,
        state_publish_hz=args.state_hz or env.state_publish_hz,
        messaging_backend=args.messaging_backend or env.messaging_backend,
        messaging_urls=messaging_urls,
        nats_credentials_file=credentials_file or env.nats_credentials_file,
        allow_insecure=args.allow_insecure or env.allow_insecure,
        portal=portal,
        portal_credentials_glob=args.portal_credentials_glob or env.portal_credentials_glob,
        portal_credentials_dir=args.portal_credentials_dir or env.portal_credentials_dir,
        discovery_mode=env.discovery_mode,
    )
    config = apply_portal_config(
        config,
        portal_credentials=portal_credentials,
        explicit_device_id=args.device_id,
        explicit_tenant=args.tenant,
    )
    return DeviceConnectRunParams(driver_config=config, portal_credentials=portal_credentials)


def _build_teleop(cfg: DriverConfig) -> TeleopComposer | None:
    if not cfg.leader_port and not cfg.enable_keyboard_teleop:
        return None
    return TeleopComposer(
        TeleopConfig(
            leader_port=cfg.leader_port,
            enable_keyboard=cfg.enable_keyboard_teleop,
        )
    )


async def run_device_connect(params: DeviceConnectRunParams) -> None:
    configure_driver_logging()
    cfg = params.driver_config
    log_run_config(params)

    if cfg.discovery_mode:
        os.environ.setdefault("DEVICE_CONNECT_DISCOVERY_MODE", cfg.discovery_mode)

    calibration_dir = Path(cfg.calibration_dir) if cfg.calibration_dir else None
    robot = build_robot_bridge(
        mode=cfg.robot_mode,
        robot_id=cfg.robot_id,
        port=cfg.robot_port,
        remote_ip=cfg.remote_ip,
        calibration_dir=calibration_dir,
    )
    teleop = _build_teleop(cfg)
    driver = LeRobotDeviceDriver(
        robot,
        teleop=teleop,
        state_publish_hz=cfg.state_publish_hz,
    )
    runtime = DeviceRuntime(
        driver=driver,
        device_id=cfg.device_id,
        tenant=cfg.tenant,
        messaging_backend=cfg.messaging_backend,
        messaging_urls=list(cfg.messaging_urls) or None,
        nats_credentials_file=cfg.nats_credentials_file,
        allow_insecure=cfg.allow_insecure,
    )

    logger.info("Starting DeviceRuntime (messaging + robot connect)")
    try:
        await runtime.run()
    except Exception:
        logger.exception("Device Connect runtime failed")
        raise
    logger.info("Device Connect runtime finished")
