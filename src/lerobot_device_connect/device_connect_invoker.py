"""Invoke lerobot-device-connect RPCs on a remote device over Device Connect messaging."""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from device_connect_edge.messaging import create_client
from device_connect_edge.messaging.base import MessagingClient
from device_connect_edge.messaging.exceptions import RequestTimeoutError

from lerobot_device_connect.config import DriverConfig, PORTAL_NATS_URL

logger = logging.getLogger(__name__)


class DeviceConnectRpcError(RuntimeError):
    """Raised when a JSON-RPC call to a device returns an error."""


@dataclass(frozen=True)
class InvokerConfig:
    """Messaging settings for calling a robot device over the mesh."""

    target_device_id: str
    tenant: str = "default"
    messaging_backend: str = "nats"
    messaging_urls: tuple[str, ...] = ()
    nats_credentials_file: str | None = None
    allow_insecure: bool = False
    rpc_timeout: float = 30.0

    @classmethod
    def from_driver_config(cls, cfg: DriverConfig, *, target_device_id: str) -> InvokerConfig:
        urls = cfg.messaging_urls
        if not urls and cfg.portal:
            urls = (PORTAL_NATS_URL,)
        return cls(
            target_device_id=target_device_id,
            tenant=cfg.tenant,
            messaging_backend=cfg.messaging_backend or "nats",
            messaging_urls=urls,
            nats_credentials_file=cfg.nats_credentials_file,
            allow_insecure=cfg.allow_insecure,
        )


def _sign_nonce(nkey_seed: str, nonce: bytes | str) -> bytes:
    try:
        import nkeys
    except ImportError as exc:
        raise ImportError("nkeys required for NATS JWT auth (pip install nkeys)") from exc

    if isinstance(nonce, str):
        nonce = nonce.encode()
    kp = nkeys.from_seed(nkey_seed.encode())
    return base64.b64encode(kp.sign(nonce))


def _load_credentials_file(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_messaging_connect(
    config: InvokerConfig,
) -> tuple[list[str], str, dict[str, Any] | None, dict[str, Any] | None]:
    """Return (servers, backend, auth_dict, tls_dict)."""
    backend = config.messaging_backend.lower()
    urls = list(config.messaging_urls) or [PORTAL_NATS_URL]
    auth: dict[str, Any] | None = None
    tls: dict[str, Any] | None = None

    if config.allow_insecure:
        return urls, backend, None, None

    creds_path = config.nats_credentials_file or os.getenv("NATS_CREDENTIALS_FILE")
    if creds_path:
        creds = _load_credentials_file(creds_path)
        block = creds.get(backend, creds.get("nats", {}))
        if block.get("urls"):
            urls = list(block["urls"])
        jwt = block.get("jwt")
        nkey_seed = block.get("nkey_seed")
        if jwt or nkey_seed:
            auth = {}
            if jwt:
                auth["jwt"] = jwt
            if nkey_seed:
                auth["nkey_seed"] = nkey_seed
                auth["signature_cb"] = lambda nonce, seed=nkey_seed: _sign_nonce(seed, nonce)
        tls_block = block.get("tls") or {}
        if tls_block:
            tls = dict(tls_block)

    ca_file = os.getenv("MESSAGING_TLS_CA_FILE")
    if ca_file:
        tls = tls or {}
        tls.setdefault("ca_file", ca_file)
    cert_file = os.getenv("MESSAGING_TLS_CERT_FILE")
    key_file = os.getenv("MESSAGING_TLS_KEY_FILE")
    if cert_file and key_file:
        tls = tls or {}
        tls.setdefault("cert_file", cert_file)
        tls.setdefault("key_file", key_file)

    return urls, backend, auth, tls


class DeviceConnectInvoker:
    """JSON-RPC client for a single registered robot device."""

    def __init__(self, config: InvokerConfig) -> None:
        self._config = config
        self._messaging: MessagingClient | None = None

    @property
    def target_device_id(self) -> str:
        return self._config.target_device_id

    @property
    def tenant(self) -> str:
        return self._config.tenant

    async def connect(self) -> None:
        if self._messaging is not None and self._messaging.is_connected:
            return
        urls, backend, auth, tls = _resolve_messaging_connect(self._config)
        self._messaging = create_client(backend)
        await self._messaging.connect(
            servers=urls,
            credentials=auth,
            tls_config=tls,
        )
        logger.info(
            "Device Connect invoker connected (target=%s tenant=%s urls=%s)",
            self._config.target_device_id,
            self._config.tenant,
            urls,
        )

    async def disconnect(self) -> None:
        if self._messaging is None:
            return
        await self._messaging.disconnect()
        self._messaging = None
        logger.info("Device Connect invoker disconnected")

    async def invoke(self, function_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call an RPC on the target device; return the driver's result dict."""
        if self._messaging is None or not self._messaging.is_connected:
            raise RuntimeError("not connected to messaging")

        params = dict(params or {})
        req_id = f"web-{uuid.uuid4().hex[:12]}"
        subject = f"device-connect.{self._config.tenant}.{self._config.target_device_id}.cmd"
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": function_name,
            "params": params,
        }
        try:
            raw = await self._messaging.request(
                subject,
                json.dumps(payload).encode(),
                timeout=self._config.rpc_timeout,
            )
        except RequestTimeoutError as exc:
            raise DeviceConnectRpcError(
                f"timeout calling {function_name!r} on {self._config.target_device_id!r}"
            ) from exc

        response = json.loads(raw.decode())
        if "error" in response:
            err = response["error"]
            raise DeviceConnectRpcError(
                f"{function_name}: {err.get('message', err)} (code {err.get('code')})"
            )
        result = response.get("result")
        if isinstance(result, dict):
            return result
        return {"status": "success", "result": result}
