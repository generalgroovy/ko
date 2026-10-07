import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from ko2_daw.gui import KO2DawApp
from ko2_daw.samples import SampleLibrary


def workspace(tmp_path):
    view = KO2DawApp.__new__(KO2DawApp)
    view.sample_library = SampleLibrary()
    view.sample_saved_rows = ()
    view.sample_manifest_path = None
    view.sample_save_status = Mock()
    view.project_root = tmp_path
    view._set_action = Mock()
    view._refresh_sample_tree = Mock(side_effect=view._update_sample_save_status)
    view._log = Mock()
    audio = tmp_path / "kick.wav"
    with wave.open(str(audio), "wb") as writer:
        writer.setparams((1, 2, 8000, 80, "NONE", "not compressed"))
        writer.writeframes(b"\0\0" * 80)
    return view, audio


def test_import_save_and_addition_explain_current_persistence(tmp_path, monkeypatch):
    view, audio = workspace(tmp_path)
    monkeypatch.setattr("ko2_daw.gui.filedialog.askopenfilenames", lambda **kw: [str(audio)])
    view._import_wav()
    assert "Unsaved" in view.sample_save_status.set.call_args.args[0]
    destination = tmp_path / "my-library.json"
    picker = Mock(return_value=str(destination))
    monkeypatch.setattr("ko2_daw.gui.filedialog.asksaveasfilename", picker)
    notice = Mock()
    monkeypatch.setattr("ko2_daw.gui.messagebox.showinfo", notice)
    view._save_sample_manifest()
    assert SampleLibrary.load(destination).ordered() == view.sample_library.ordered()
    assert "Saved: my-library.json" in view.sample_save_status.set.call_args.args[0]
    assert "not audio" in view._set_action.call_args.args[0]
    notice.assert_not_called()
    view.sample_tree = Mock()
    view._add_sample_copies([audio])
    assert "Unsaved" in view.sample_save_status.set.call_args.args[0]
    picker.return_value = ""
    view._save_sample_manifest()
    assert picker.call_args.kwargs["initialfile"] == "my-library.json"
    assert picker.call_args.kwargs["initialdir"] == tmp_path
    assert len(SampleLibrary.load(destination).samples) == 1
    assert "Unsaved" in view.sample_save_status.set.call_args.args[0]


def test_same_count_metadata_change_is_unsaved_and_reversion_is_clean(tmp_path):
    view, audio = workspace(tmp_path)
    original = view.sample_library.add_wav(audio)
    view._mark_sample_library_saved(tmp_path / "library.json")
    view.sample_library.samples[original.slot] = replace(original, name="New name")
    view._update_sample_save_status()
    assert "Unsaved" in view.sample_save_status.set.call_args.args[0]
    view.sample_library.samples[original.slot] = original
    view._update_sample_save_status()
    assert "Saved: library.json" in view.sample_save_status.set.call_args.args[0]


@pytest.mark.parametrize("cancel", [True, False])
def test_cancelled_or_failed_save_preserves_last_saved_baseline(tmp_path, monkeypatch, cancel):
    view, audio = workspace(tmp_path)
    view.sample_library.add_wav(audio)
    view._mark_sample_library_saved(tmp_path / "previous.json")
    before = view.sample_saved_rows
    view.sample_library.add_wav(audio)
    view._update_sample_save_status()
    monkeypatch.setattr(
        "ko2_daw.gui.filedialog.asksaveasfilename",
        lambda **kw: "" if cancel else str(tmp_path / "new.json"),
    )
    view.sample_library.save = Mock(side_effect=OSError("Destination unavailable"))
    error = Mock()
    monkeypatch.setattr("ko2_daw.gui.messagebox.showerror", error)
    view._save_sample_manifest()
    assert view.sample_saved_rows == before
    assert view.sample_manifest_path == tmp_path / "previous.json"
    assert "Unsaved" in view.sample_save_status.set.call_args.args[0]
    assert error.call_count == (0 if cancel else 1)


def test_open_updates_save_target_only_when_replacement_succeeds(tmp_path, monkeypatch):
    view, audio = workspace(tmp_path)
    library = SampleLibrary()
    library.add_wav(audio, slot=8)
    target = library.save(tmp_path / "opened.json")
    view.sample_library.add_wav(audio)
    monkeypatch.setattr("ko2_daw.gui.filedialog.askopenfilename", lambda **kw: str(target))
    monkeypatch.setattr("ko2_daw.gui.messagebox.askyesno", lambda *a: False)
    view._open_sample_manifest()
    assert view.sample_manifest_path is None
    monkeypatch.setattr("ko2_daw.gui.messagebox.askyesno", lambda *a: True)
    view._open_sample_manifest()
    assert view.sample_manifest_path == Path(target)
    assert view.sample_saved_rows == tuple(library.ordered())
    assert "Saved: opened.json" in view.sample_save_status.set.call_args.args[0]
