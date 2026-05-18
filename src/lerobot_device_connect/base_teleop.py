"""LeKiwi omniwheel base velocity helpers (keyboard teleop semantics)."""

from __future__ import annotations

from typing import Any

# Matches ``LeKiwiClient.speed_levels`` defaults.
DEFAULT_SPEED_LEVELS: tuple[dict[str, float], ...] = (
    {"xy": 0.1, "theta": 30},
    {"xy": 0.2, "theta": 60},
    {"xy": 0.3, "theta": 90},
)

BASE_DIRECTIONS: frozenset[str] = frozenset(
    {
        "forward",
        "backward",
        "left",
        "right",
        "rotate_left",
        "rotate_right",
        "stop",
    }
)


def clamp_speed_index(index: int, *, num_levels: int = 3) -> int:
    return max(0, min(index, num_levels - 1))


def base_velocity_for_directions(
    directions: set[str] | frozenset[str],
    *,
    speed_index: int,
    speed_levels: tuple[dict[str, float], ...] = DEFAULT_SPEED_LEVELS,
) -> dict[str, float]:
    """Map teleop direction names to body-frame velocities (m/s, deg/s)."""
    if "stop" in directions:
        return {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}

    index = clamp_speed_index(speed_index, num_levels=len(speed_levels))
    speed = speed_levels[index]
    xy_speed = float(speed["xy"])
    theta_speed = float(speed["theta"])

    x_cmd = 0.0
    y_cmd = 0.0
    theta_cmd = 0.0

    if "forward" in directions:
        x_cmd += xy_speed
    if "backward" in directions:
        x_cmd -= xy_speed
    if "left" in directions:
        y_cmd += xy_speed
    if "right" in directions:
        y_cmd -= xy_speed
    if "rotate_left" in directions:
        theta_cmd += theta_speed
    if "rotate_right" in directions:
        theta_cmd -= theta_speed

    return {"x.vel": x_cmd, "y.vel": y_cmd, "theta.vel": theta_cmd}


def base_teleop_config(
    *,
    speed_index: int,
    speed_levels: tuple[dict[str, float], ...] = DEFAULT_SPEED_LEVELS,
) -> dict[str, Any]:
    """JSON-serializable teleop parameters for RPC clients."""
    return {
        "speed_index": clamp_speed_index(speed_index, num_levels=len(speed_levels)),
        "speed_levels": [dict(level) for level in speed_levels],
        "directions": sorted(BASE_DIRECTIONS),
    }
