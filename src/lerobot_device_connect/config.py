"""Runtime configuration for the LeRobot Device Connect driver."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PORTAL_NATS_URL = "nats://portal.deviceconnect.dev:4222"
DEFAULT_PORTAL_CREDENTIALS_GLOB = "erivan01*.json"
DEFAULT_PORTAL_CREDENTIALS_DIR = Path.home() / "Downloads"


@dataclass(frozen=True)
class PortalCredentials:
    path: Path
    device_id: str | None = None
    tenant: str | None = None
    messaging_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class DriverConfig:
    device_id: str = "lekiwi-1"
    tenant: str = "default"
    robot_mode: str = "local"
    robot_id: str = "lekiwi"
    robot_port: str = "/dev/ttyACM0"
    remote_ip: str | None = None
    leader_port: str | None = None
    enable_keyboard_teleop: bool = False
    state_publish_hz: float = 10.0
    messaging_backend: str | None = None
    messaging_urls: tuple[str, ...] = ()
    nats_credentials_file: str | None = None
    allow_insecure: bool = False
    portal: bool = False
    portal_credentials_glob: str = DEFAULT_PORTAL_CREDENTIALS_GLOB
    portal_credentials_dir: str = str(DEFAULT_PORTAL_CREDENTIALS_DIR)
    discovery_mode: str | None = None

    @classmethod
    def from_env(cls) -> DriverConfig:
        urls = tuple(
            url.strip()
            for url in os.environ.get("MESSAGING_URLS", os.environ.get("NATS_URL", "")).split(",")
            if url.strip()
        )
        allow_insecure = os.environ.get("DEVICE_CONNECT_ALLOW_INSECURE", "").lower()
        return cls(
            device_id=os.environ.get("DEVICE_ID", os.environ.get("LEROBOT_DEVICE_ID", "lekiwi-1")),
            tenant=os.environ.get("TENANT", os.environ.get("LEROBOT_TENANT", "default")),
            robot_mode=os.environ.get("LEROBOT_ROBOT_MODE", "local"),
            robot_id=os.environ.get("LEROBOT_ROBOT_ID", "lekiwi"),
            robot_port=os.environ.get("LEROBOT_ROBOT_PORT", "/dev/ttyACM0"),
            remote_ip=os.environ.get("LEROBOT_REMOTE_IP") or None,
            leader_port=os.environ.get("LEROBOT_TELEOP_LEADER_PORT") or None,
            enable_keyboard_teleop=_truthy(os.environ.get("LEROBOT_TELEOP_KEYBOARD", "")),
            state_publish_hz=float(os.environ.get("LEROBOT_STATE_HZ", "10")),
            messaging_backend=os.environ.get("MESSAGING_BACKEND") or None,
            messaging_urls=urls,
            nats_credentials_file=(
                os.environ.get("NATS_CREDENTIALS_FILE")
                or os.environ.get("PORTAL_CREDENTIALS_FILE")
                or None
            ),
            allow_insecure=allow_insecure in {"1", "true", "yes"},
            portal=_truthy(os.environ.get("DEVICE_CONNECT_PORTAL", "")),
            portal_credentials_glob=os.environ.get(
                "PORTAL_CREDENTIALS_GLOB",
                DEFAULT_PORTAL_CREDENTIALS_GLOB,
            ),
            portal_credentials_dir=os.environ.get(
                "PORTAL_CREDENTIALS_DIR",
                str(DEFAULT_PORTAL_CREDENTIALS_DIR),
            ),
            discovery_mode=os.environ.get("DEVICE_CONNECT_DISCOVERY_MODE") or None,
        )


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_portal_credentials_file(
    *,
    explicit_path: str | None,
    portal: bool,
    pattern: str,
    search_dir: str,
) -> str | None:
    if explicit_path:
        return explicit_path
    if not portal:
        return None
    root = Path(search_dir)
    if not root.is_dir():
        return None
    matches = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(matches[0]) if matches else None


def load_portal_credentials(path: str) -> PortalCredentials:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    urls: list[str] = []
    if isinstance(data.get("servers"), list):
        urls.extend(str(s) for s in data["servers"])
    if data.get("url"):
        urls.append(str(data["url"]))
    if not urls:
        urls.append(PORTAL_NATS_URL)
    return PortalCredentials(
        path=Path(path),
        device_id=data.get("device_id") or data.get("deviceId"),
        tenant=data.get("tenant"),
        messaging_urls=tuple(urls),
    )


def apply_portal_config(
    config: DriverConfig,
    *,
    portal_credentials: PortalCredentials | None,
    explicit_device_id: str | None,
    explicit_tenant: str | None,
) -> DriverConfig:
    if not portal_credentials and not config.portal:
        return config
    device_id = explicit_device_id or portal_credentials.device_id if portal_credentials else None
    tenant = explicit_tenant or portal_credentials.tenant if portal_credentials else None
    urls = portal_credentials.messaging_urls if portal_credentials else config.messaging_urls
    creds = str(portal_credentials.path) if portal_credentials else config.nats_credentials_file
    return DriverConfig(
        device_id=device_id or config.device_id,
        tenant=tenant or config.tenant,
        robot_mode=config.robot_mode,
        robot_id=config.robot_id,
        robot_port=config.robot_port,
        remote_ip=config.remote_ip,
        leader_port=config.leader_port,
        enable_keyboard_teleop=config.enable_keyboard_teleop,
        state_publish_hz=config.state_publish_hz,
        messaging_backend=config.messaging_backend or "nats",
        messaging_urls=urls or (PORTAL_NATS_URL,),
        nats_credentials_file=creds,
        allow_insecure=config.allow_insecure,
        portal=True,
        portal_credentials_glob=config.portal_credentials_glob,
        portal_credentials_dir=config.portal_credentials_dir,
        discovery_mode=config.discovery_mode,
    )
