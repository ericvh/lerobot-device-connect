"""Camera video and optional ALSA audio capture for Device Connect RPCs."""

from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from lerobot_device_connect.observation_codec import encode_camera_frame

logger = logging.getLogger(__name__)

_VIDEO_DEVICE_RE = re.compile(r"video(\d+)")


def camera_names_from_features(features: dict[str, Any]) -> list[str]:
    """Return camera keys from LeRobot observation feature schemas."""
    names: list[str] = []
    for key, ft in features.items():
        if isinstance(ft, str) and ft.startswith("image"):
            names.append(key)
        elif isinstance(ft, tuple) and len(ft) >= 3:
            names.append(key)
    return sorted(names)


def extract_camera_frame(observation: dict[str, Any], camera: str) -> np.ndarray | None:
    frame = observation.get(camera)
    if isinstance(frame, np.ndarray) and frame.ndim >= 2:
        return frame
    return None


def encode_camera_from_observation(
    observation: dict[str, Any],
    camera: str,
    *,
    jpeg_quality: int = 85,
) -> dict[str, Any]:
    """Encode one camera frame from a robot observation dict."""
    frame = extract_camera_frame(observation, camera)
    if frame is None:
        return {"status": "error", "reason": f"camera {camera!r} not in observation"}
    encoded = encode_camera_frame(frame, jpeg_quality=jpeg_quality)
    if encoded.get("status") != "success":
        return encoded
    return {"status": "success", "camera": camera, **encoded}


def encode_all_cameras_from_observation(
    observation: dict[str, Any],
    *,
    camera_names: list[str],
    jpeg_quality: int = 85,
) -> dict[str, Any]:
    """Encode all named cameras present in *observation*."""
    cameras: dict[str, Any] = {}
    errors: list[str] = []
    for name in camera_names:
        result = encode_camera_from_observation(observation, name, jpeg_quality=jpeg_quality)
        if result.get("status") == "success":
            cameras[name] = {k: v for k, v in result.items() if k not in {"status", "camera"}}
        else:
            errors.append(result.get("reason", f"{name}: unknown error"))
    payload: dict[str, Any] = {"status": "success", "cameras": cameras}
    if errors:
        payload["errors"] = errors
    return payload


def alsa_device_for_v4l2_path(video_path: str | int) -> str | None:
    """Resolve an ALSA capture device for a V4L2 node (e.g. ``/dev/video0`` → ``hw:2,0``)."""
    path = str(video_path)
    match = _VIDEO_DEVICE_RE.search(path)
    if not match:
        return None
    sysfs_device = Path(f"/sys/class/video4linux/video{match.group(1)}/device")
    if not sysfs_device.exists():
        return None
    resolved = sysfs_device.resolve()
    for parent in (resolved, *resolved.parents):
        sound_dir = parent / "sound"
        if not sound_dir.is_dir():
            continue
        for card in sorted(sound_dir.glob("card*")):
            card_num = card.name.removeprefix("card")
            if card_num.isdigit():
                return f"hw:{card_num},0"
    return None


def _capture_alsa_with_arecord(
    alsa_device: str,
    *,
    duration_ms: int,
    sample_rate: int,
) -> bytes | None:
    """Capture WAV via ``arecord`` when available (common on Raspberry Pi)."""
    import shutil
    import subprocess
    import tempfile

    if shutil.which("arecord") is None:
        return None

    duration_s = max(0.05, duration_ms / 1000.0)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    cmd = [
        "arecord",
        "-D",
        alsa_device,
        "-d",
        f"{duration_s:.2f}",
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        "1",
        "-q",
        str(wav_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=duration_s + 5.0)
        return wav_path.read_bytes()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("arecord failed for %s: %s", alsa_device, exc)
        return None
    finally:
        wav_path.unlink(missing_ok=True)


def capture_alsa_audio(
    alsa_device: str,
    *,
    duration_ms: int = 500,
    sample_rate: int = 16000,
) -> dict[str, Any]:
    """Capture a short PCM clip and return WAV bytes as base64."""
    duration_ms = max(50, min(duration_ms, 10_000))
    sample_rate = max(8_000, min(sample_rate, 48_000))

    wav_bytes = _capture_alsa_with_arecord(
        alsa_device,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
    )
    if wav_bytes:
        return {
            "status": "success",
            "encoding": "wav",
            "sample_rate": sample_rate,
            "duration_ms": duration_ms,
            "alsa_device": alsa_device,
            "capture_backend": "arecord",
            "data_b64": base64.b64encode(wav_bytes).decode("utf-8"),
        }

    try:
        import av
    except ImportError as exc:
        return {"status": "error", "reason": f"no capture backend (arecord/PyAV): {exc}"}

    max_samples = int(sample_rate * duration_ms / 1000)

    try:
        container = av.open(
            alsa_device,
            format="alsa",
            mode="r",
            timeout=5.0,
            options={"sample_rate": str(sample_rate), "channels": "1"},
        )
    except Exception as exc:
        return {"status": "error", "reason": f"failed to open {alsa_device!r}: {exc}"}

    try:
        import wave

        stream = container.streams.audio[0]
        pcm_chunks: list[bytes] = []
        samples_read = 0
        for packet in container.demux(stream):
            for frame in packet.decode():
                array = frame.to_ndarray()
                if array.dtype != np.int16:
                    array = (array * 32767).astype(np.int16)
                pcm_chunks.append(array.tobytes())
                samples_read += frame.samples
                if samples_read >= max_samples:
                    break
            if samples_read >= max_samples:
                break
    except Exception as exc:
        return {"status": "error", "reason": f"audio capture failed: {exc}"}
    finally:
        container.close()

    if not pcm_chunks:
        return {"status": "error", "reason": "no audio samples captured"}

    wav_buffer = io.BytesIO()
    try:
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"".join(pcm_chunks)[: max_samples * 2])
    except Exception as exc:
        return {"status": "error", "reason": f"wav encode failed: {exc}"}

    return {
        "status": "success",
        "encoding": "wav",
        "sample_rate": sample_rate,
        "duration_ms": duration_ms,
        "alsa_device": alsa_device,
        "capture_backend": "pyav",
        "data_b64": base64.b64encode(wav_buffer.getvalue()).decode("utf-8"),
    }


def resolve_camera_audio_devices(
    camera_video_paths: dict[str, str | int],
    *,
    overrides: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """Map camera names to ALSA devices (explicit overrides, then sysfs discovery)."""
    overrides = overrides or {}
    resolved: dict[str, str | None] = {}
    for name, video_path in camera_video_paths.items():
        if name in overrides:
            resolved[name] = overrides[name]
            continue
        resolved[name] = alsa_device_for_v4l2_path(video_path)
    return resolved
