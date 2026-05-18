"""Tests for per-host calibration path resolution."""

from __future__ import annotations

from pathlib import Path

from lerobot_device_connect.config import default_calibration_dir, default_robot_id


def test_default_robot_id_is_hostname_stem() -> None:
    assert default_robot_id()
    assert "." not in default_robot_id()


def test_default_calibration_dir_uses_home_when_file_exists(tmp_path: Path, monkeypatch) -> None:
    robot_id = "test-robot"
    calibration_file = tmp_path / f"{robot_id}.json"
    calibration_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "lerobot_device_connect.config.Path.home",
        staticmethod(lambda: tmp_path),
    )
    assert default_calibration_dir(robot_id) == tmp_path


def test_default_calibration_dir_none_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "lerobot_device_connect.config.Path.home",
        staticmethod(lambda: tmp_path),
    )
    assert default_calibration_dir("missing-robot") is None


def test_dum_e_calibration_file_on_this_host() -> None:
    """Sanity check for the user's on-device layout (~/dum-e.json)."""
    robot_id = default_robot_id()
    if robot_id != "dum-e":
        return
    assert (Path.home() / "dum-e.json").is_file()
    assert default_calibration_dir(robot_id) == Path.home()
