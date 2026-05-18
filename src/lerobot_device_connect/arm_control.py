"""LeKiwi arm joint helpers for Device Connect RPCs."""

from __future__ import annotations

from typing import Any

ARM_JOINTS: tuple[str, ...] = (
    "arm_shoulder_pan",
    "arm_shoulder_lift",
    "arm_elbow_flex",
    "arm_wrist_flex",
    "arm_wrist_roll",
    "arm_gripper",
)

_ARM_JOINT_SET = frozenset(ARM_JOINTS)
_SHORT_NAMES = {joint.removeprefix("arm_"): joint for joint in ARM_JOINTS}


def position_key(joint: str) -> str:
    """Motor-space position key for a normalized arm joint name."""
    return f"{joint}.pos"


def normalize_arm_joint(name: str) -> str | None:
    """Map RPC joint names to canonical ``arm_*`` motor names."""
    key = name.strip().lower().replace("-", "_")
    if key.endswith(".pos"):
        key = key[:-4]
    if key in _ARM_JOINT_SET:
        return key
    if key in _SHORT_NAMES:
        return _SHORT_NAMES[key]
    return None


def arm_config(*, action_features: dict[str, Any] | None = None) -> dict[str, Any]:
    """JSON-serializable arm joint metadata for RPC clients."""
    if action_features:
        joints = sorted(
            key.removesuffix(".pos")
            for key in action_features
            if key.endswith(".pos") and key.startswith("arm_")
        )
    else:
        joints = list(ARM_JOINTS)
    return {
        "joints": joints,
        "short_names": {joint.removeprefix("arm_"): joint for joint in joints},
        "position_keys": [position_key(joint) for joint in joints],
    }


def extract_arm_positions(scalars: dict[str, float | int | str]) -> dict[str, float]:
    """Return ``{joint: position}`` from a scalar observation dict."""
    positions: dict[str, float] = {}
    for key, value in scalars.items():
        if not key.endswith(".pos") or not key.startswith("arm_"):
            continue
        joint = key.removesuffix(".pos")
        positions[joint] = float(value)
    return positions


def build_arm_position_action(
    positions: dict[str, float],
    *,
    zero_base: bool = True,
) -> dict[str, float]:
    """Build a motor-space action dict from joint → position mappings."""
    action: dict[str, float] = {}
    for joint_name, value in positions.items():
        joint = normalize_arm_joint(joint_name)
        if joint is None:
            raise ValueError(
                f"unknown arm joint {joint_name!r}; use one of {sorted(_SHORT_NAMES)} "
                f"or {sorted(ARM_JOINTS)}",
            )
        action[position_key(joint)] = float(value)
    if zero_base:
        action.update({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
    return action


def parse_arm_position_updates(
    positions: dict[str, float],
) -> tuple[dict[str, float], list[str]]:
    """Normalize *positions*; return ``(canonical joint → value, unknown inputs)``."""
    parsed: dict[str, float] = {}
    unknown: list[str] = []
    for joint_name, value in positions.items():
        joint = normalize_arm_joint(joint_name)
        if joint is None:
            unknown.append(joint_name)
            continue
        parsed[joint] = float(value)
    return parsed, unknown
