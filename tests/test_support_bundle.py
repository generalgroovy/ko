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


def test_support_bundle_includes_device_library_metadata_not_audio(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ko2_daw.support_bundle.midi_capability_report",
        lambda: {
            "live_midi_available": False,
            "ko2_usb_connected": False,
            "ko2_midi_ready": False,
            "ko2_midi_ports": [],
            "input_ports": [],
            "output_ports": [],
            "actions": [],
            "hints": [],
        },
    )
    bundle = tmp_path / "device_library" / "00207_sound" / "hash"
    bundle.mkdir(parents=True)
    (tmp_path / "device_library" / "project_catalog.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (bundle.parent / "latest.json").write_text("{}\n", encoding="utf-8")
    (bundle / "manifest.json").write_text("{}\n", encoding="utf-8")
    (bundle / "metadata.json").write_text("{}\n", encoding="utf-8")
    (bundle / "project_analysis.json").write_text("{}\n", encoding="utf-8")
    (bundle / "207.wav").write_bytes(b"large audio")
    audio_projects = tmp_path / "audio_projects"
    audio_projects.mkdir()
    (audio_projects / "session.json").write_text("{}\n", encoding="utf-8")
    (audio_projects / "session.wav").write_bytes(b"private recording")

    path = create_support_bundle(tmp_path, project_root=tmp_path)

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert any(name.endswith("/latest.json") for name in names)
        assert any(name.endswith("/manifest.json") for name in names)
        assert any(name.endswith("/metadata.json") for name in names)
        assert any(name.endswith("/project_analysis.json") for name in names)
        assert any(name.endswith("/device_library/project_catalog.json") for name in names)
        assert any(name.endswith("/audio_projects/session.json") for name in names)
        assert not any(name.endswith(".wav") for name in names)
