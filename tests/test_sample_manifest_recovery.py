import json
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ko2_daw.gui import KO2DawApp
from ko2_daw.samples import SampleLibrary


def saved_library(tmp_path):
    audio = tmp_path / "kick.wav"
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 80)
    library = SampleLibrary()
    library.add_wav(audio, slot=8)
    return library, library.save(tmp_path / "samples.json")


def test_reopen_resolves_relative_audio_and_reads_actual_format(tmp_path):
    library, manifest = saved_library(tmp_path)
    data = json.loads(manifest.read_text())
    data["samples"][0].update(path="kick.wav", frames=9999, sample_rate=1)
    manifest.write_text(json.dumps(data))
    assert SampleLibrary.load(manifest).ordered() == library.ordered()


@pytest.mark.parametrize("slot", [True, 1.5, "8", -1, 999, None])
def test_bad_slot_is_rejected_before_audio_reads(tmp_path, slot):
    _, manifest = saved_library(tmp_path)
    data = json.loads(manifest.read_text())
    data["samples"][0]["slot"] = slot
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Sample slot"):
        SampleLibrary.load(manifest)


def test_duplicate_slots_are_not_silently_overwritten(tmp_path):
    _, manifest = saved_library(tmp_path)
    data = json.loads(manifest.read_text())
    data["samples"] *= 2
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Duplicate sample slot"):
        SampleLibrary.load(manifest)


@pytest.mark.parametrize("payload", [[], {}, {"samples": []}, {"schema": "other", "samples": []}])
def test_wrong_format_is_not_accepted_as_an_empty_library(tmp_path, payload):
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="desktop sample manifest"):
        SampleLibrary.load(manifest)


def test_gui_load_failure_or_cancel_keeps_current_table(tmp_path, monkeypatch):
    library, manifest = saved_library(tmp_path)
    view = SimpleNamespace(sample_library=library, _refresh_sample_tree=Mock(), _set_action=Mock())
    monkeypatch.setattr("ko2_daw.gui.filedialog.askopenfilename", lambda **kwargs: str(manifest))
    monkeypatch.setattr("ko2_daw.gui.messagebox.askyesno", lambda *args: False)
    error = Mock()
    monkeypatch.setattr("ko2_daw.gui.messagebox.showerror", error)
    KO2DawApp._open_sample_manifest(view)
    assert view.sample_library is library
    view._refresh_sample_tree.assert_not_called()
    data = json.loads(manifest.read_text())
    data["samples"][0]["path"] = "missing.wav"
    manifest.write_text(json.dumps(data))
    KO2DawApp._open_sample_manifest(view)
    assert view.sample_library is library
    error.assert_called_once()


def test_gui_open_restores_table_and_save_cancel_does_not_write(tmp_path, monkeypatch):
    library, manifest = saved_library(tmp_path)
    view = SimpleNamespace(
        sample_library=SampleLibrary(),
        project_root=tmp_path,
        _refresh_sample_tree=Mock(),
        _set_action=Mock(),
        _mark_sample_library_saved=Mock(),
    )
    monkeypatch.setattr("ko2_daw.gui.filedialog.askopenfilename", lambda **kwargs: str(manifest))
    KO2DawApp._open_sample_manifest(view)
    assert view.sample_library.ordered() == library.ordered()
    view._refresh_sample_tree.assert_called_once()
    view.sample_library.save = Mock()
    monkeypatch.setattr("ko2_daw.gui.filedialog.asksaveasfilename", lambda **kwargs: "")
    KO2DawApp._save_sample_manifest(view)
    view.sample_library.save.assert_not_called()
