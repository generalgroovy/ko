"""Tests for native WinMM audio capture helpers."""

from __future__ import annotations

import sys

import pytest

from ko2_daw.native_audio import (
    WaveInputDevice,
    _resolve_wave_input,
    list_wave_input_devices,
    record_wave_input,
)


def test_resolve_wave_input_exact_partial_ambiguous_and_id() -> None:
    devices = [
        WaveInputDevice(0, "MAIN (QUAD-CAPTURE)", 2, 0),
        WaveInputDevice(1, "1-2 (QUAD-CAPTURE)", 2, 0),
    ]

    assert _resolve_wave_input(devices, device_name="MAIN", device_id=None).device_id == 0
    assert _resolve_wave_input(devices, device_name=None, device_id=1).name.startswith("1-2")
    with pytest.raises(ValueError, match="ambiguous"):
        _resolve_wave_input(devices, device_name="QUAD-CAPTURE", device_id=None)
    with pytest.raises(ValueError, match="not visible"):
        _resolve_wave_input(devices, device_name="missing", device_id=None)


@pytest.mark.skipif(sys.platform != "win32", reason="WinMM is Windows-only")
def test_windows_exposes_at_least_one_wave_input() -> None:
    devices = list_wave_input_devices()

    assert devices
    assert all(device.name and device.channels >= 1 for device in devices)


def test_capture_rejects_invalid_bounds_before_opening_hardware(tmp_path) -> None:
    with pytest.raises(ValueError, match="duration"):
        record_wave_input(tmp_path / "bad.wav", duration_sec=0)
    with pytest.raises(ValueError, match="sample rate"):
        record_wave_input(tmp_path / "bad.wav", sample_rate=12345)
