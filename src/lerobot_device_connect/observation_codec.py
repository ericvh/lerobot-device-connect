"""Serialize LeRobot observations for Device Connect RPC payloads."""

from __future__ import annotations

import base64
from typing import Any

import cv2
import numpy as np


def _is_numpy_array(value: object) -> bool:
    return isinstance(value, np.ndarray)


def scalar_observation(observation: dict[str, Any]) -> dict[str, float | int | str]:
    """Return only JSON-safe scalar fields from a robot observation."""
    result: dict[str, float | int | str] = {}
    for key, value in observation.items():
        if _is_numpy_array(value):
            continue
        if isinstance(value, (float, int, str, bool)):
            result[key] = float(value) if isinstance(value, bool) else value
        elif hasattr(value, "item"):
            try:
                result[key] = float(value.item())
            except (TypeError, ValueError):
                continue
    return result


def encode_camera_frame(frame: np.ndarray, *, jpeg_quality: int = 85) -> dict[str, Any]:
    """Encode an OpenCV BGR frame as a base64 JPEG."""
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        return {"status": "error", "reason": "jpeg encode failed"}
    return {
        "status": "success",
        "encoding": "jpeg",
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
        "channels": int(frame.shape[2]) if frame.ndim == 3 else 1,
        "data_b64": base64.b64encode(buffer).decode("utf-8"),
    }


def observation_with_cameras(
    observation: dict[str, Any],
    *,
    jpeg_quality: int = 85,
) -> dict[str, Any]:
    """Scalars plus optional per-camera JPEG payloads."""
    payload: dict[str, Any] = {"scalars": scalar_observation(observation), "cameras": {}}
    for key, value in observation.items():
        if not _is_numpy_array(value):
            continue
        if value.ndim < 2:
            continue
        encoded = encode_camera_frame(value, jpeg_quality=jpeg_quality)
        if encoded.get("status") == "success":
            payload["cameras"][key] = encoded
    return payload
