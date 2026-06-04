"""Tests for support bundle export."""

import json
import zipfile

from ko2_daw.support_bundle import create_support_bundle


def test_create_support_bundle_contains_core_reports(tmp_path, monkeypatch) -> None:
    def fake_midi_report():
        return {
            "live_midi_available": True,
            "ko2_usb_connected": False,
            "ko2_midi_ready": False,
            "ko2_midi_ports": [],
            "input_ports": [],
            "output_ports": [],
            "actions": [],
            "hints": [],
        }

    monkeypatch.setattr("ko2_daw.support_bundle.midi_capability_report", fake_midi_report)
    path = create_support_bundle(
        tmp_path,
        settings_path=tmp_path / "missing_settings.json",
        project_root=tmp_path,
    )
    assert path.exists()
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "midi_report.json" in names
        assert "readiness_report.json" in names
        assert "route.json" in names
        assert "settings.json" in names
        midi_report = json.loads(archive.read("midi_report.json"))
        assert midi_report["ko2_usb_connected"] is False
