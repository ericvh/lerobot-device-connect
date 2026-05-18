"""Logging configuration for the LeRobot Device Connect driver."""

from __future__ import annotations

import logging
import os


def configure_driver_logging() -> None:
    level_name = os.environ.get("LEROBOT_DEVICE_CONNECT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("device_connect_edge").setLevel(level)
