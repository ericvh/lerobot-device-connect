"""Tests for Device Connect JSON-RPC invoker."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from lerobot_device_connect.device_connect_invoker import (
    DeviceConnectInvoker,
    DeviceConnectRpcError,
    InvokerConfig,
    _resolve_messaging_connect,
)


def test_resolve_messaging_insecure():
    cfg = InvokerConfig(
        target_device_id="robot-1",
        allow_insecure=True,
        nats_credentials_file="/unused",
    )
    urls, backend, auth, tls = _resolve_messaging_connect(cfg)
    assert backend == "nats"
    assert auth is None
    assert tls is None


@pytest.mark.asyncio
async def test_invoke_unwraps_result() -> None:
    messaging = MagicMock()
    messaging.is_connected = True
    messaging.request = AsyncMock(
        return_value=json.dumps(
            {"jsonrpc": "2.0", "id": "x", "result": {"status": "success", "connected": True}}
        ).encode(),
    )
    invoker = DeviceConnectInvoker(InvokerConfig(target_device_id="my-robot", tenant="lab"))
    invoker._messaging = messaging

    result = await invoker.invoke("get_status")
    assert result["connected"] is True
    messaging.request.assert_awaited_once()
    subject = messaging.request.await_args.args[0]
    assert subject == "device-connect.lab.my-robot.cmd"


@pytest.mark.asyncio
async def test_invoke_raises_on_json_rpc_error() -> None:
    messaging = MagicMock()
    messaging.is_connected = True
    messaging.request = AsyncMock(
        return_value=json.dumps(
            {"jsonrpc": "2.0", "id": "x", "error": {"code": -32601, "message": "Unknown method"}}
        ).encode(),
    )
    invoker = DeviceConnectInvoker(InvokerConfig(target_device_id="r"))
    invoker._messaging = messaging

    with pytest.raises(DeviceConnectRpcError, match="Unknown method"):
        await invoker.invoke("bad_method")
