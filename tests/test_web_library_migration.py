"""Offline migration contracts for the retired browser sample library."""

import json
import wave

import pytest

from ko2_daw import app
from ko2_daw.samples import MAX_SAMPLE_SLOTS, SampleLibrary


def wav_file(path):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00\x01\x00" * 80)
    return path


def manifest(path, entries):
    path.write_text(json.dumps({"samples": entries}), encoding="utf-8")
    return path


def test_browser_export_migrates_real_audio_preserving_existing_slots(tmp_path):
    existing = wav_file(tmp_path / "existing.wav")
    library = SampleLibrary()
    original = library.add_wav(existing, slot=0)
    wav_file(tmp_path / "Kick _ one.wav")
    source = manifest(
        tmp_path / "web.json",
        [
            {
                "name": "Kick / one",
                "fileName": "kick.mp3",
                "duration": 999,
                "sampleRate": 1,
                "channels": 99,
                "source": "local",
            }
        ],
    )
    assert library.import_web_manifest(source, tmp_path) == 1
    assert library.samples[0] == original
    migrated = library.samples[1]
    assert migrated.name == "Kick / one"
    assert migrated.duration_sec == 0.01
    assert migrated.sample_rate == 8000
    assert migrated.channels == 2
    assert migrated.frames == 80
    assert migrated.sample_width_bits == 16
    saved = library.save(tmp_path / "desktop.json")
    assert SampleLibrary.load(saved).ordered() == library.ordered()


@pytest.mark.parametrize(
    "entries, message",
    [
        ([{"name": "kick"}, {"name": "missing"}], "Missing exported WAV"),
        ([{"name": "kick"}, {"name": "kick"}], "Duplicate WAV"),
        ([{"name": "a/b"}, {"name": "a?b"}], "Duplicate WAV"),
        ([{"name": "kick"}, {}], "nonempty name"),
        ([None], "must be an object"),
    ],
)
def test_bad_batches_leave_library_unchanged(tmp_path, entries, message):
    wav_file(tmp_path / "kick.wav")
    wav_file(tmp_path / "a_b.wav")
    library = SampleLibrary()
    original = library.add_wav(wav_file(tmp_path / "original.wav"), slot=12)
    source = manifest(tmp_path / "web.json", entries)
    with pytest.raises(ValueError, match=message):
        library.import_web_manifest(source, tmp_path)
    assert library.ordered() == [original]


def test_existing_audio_is_not_duplicated(tmp_path):
    library = SampleLibrary()
    library.add_wav(wav_file(tmp_path / "kick.wav"))
    with pytest.raises(ValueError, match="Duplicate WAV"):
        library.import_web_manifest(manifest(tmp_path / "web.json", [{"name": "kick"}]), tmp_path)
    assert len(library.samples) == 1


@pytest.mark.parametrize("payload", [[], {}, {"samples": None}, {"samples": [], "schema": "other"}])
def test_wrong_manifest_shape_is_rejected(tmp_path, payload):
    source = tmp_path / "web.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        SampleLibrary().import_web_manifest(source, tmp_path)


def test_capacity_is_checked_before_loading_files(tmp_path):
    source = manifest(tmp_path / "web.json", [{"name": "missing"}] * (MAX_SAMPLE_SLOTS + 1))
    with pytest.raises(ValueError, match="Not enough free"):
        SampleLibrary().import_web_manifest(source, tmp_path)


def test_symlink_cannot_escape_audio_directory(tmp_path):
    folder = tmp_path / "audio"
    folder.mkdir()
    target = wav_file(tmp_path / "outside.wav")
    try:
        (folder / "kick.wav").symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks requires platform permissions")
    source = manifest(tmp_path / "web.json", [{"name": "kick"}])
    with pytest.raises(ValueError, match="outside the audio directory"):
        SampleLibrary().import_web_manifest(source, folder)


def test_cli_exports_without_querying_midi_and_protects_output(tmp_path, monkeypatch, capsys):
    def no_midi():
        pytest.fail("Local migration must not query MIDI")

    monkeypatch.setattr(app, "midi_capability_report", no_midi)
    wav_file(tmp_path / "kick.wav")
    source = manifest(tmp_path / "web.json", [{"name": "kick"}])
    output = tmp_path / "desktop.json"
    args = [
        "--import-web-manifest",
        str(source),
        "--sample-audio-dir",
        str(tmp_path),
        "--sample-manifest-output",
        str(output),
    ]
    assert app.main(args) == 0
    assert "Imported 1 local sample(s)" in capsys.readouterr().out
    before = output.read_bytes()
    with pytest.raises(SystemExit) as result:
        app.main(args)
    assert result.value.code == 2
    assert output.read_bytes() == before


def test_invalid_wav_is_clear_cli_error_without_output(tmp_path, capsys):
    (tmp_path / "kick.wav").write_bytes(b"not a wav file")
    source = manifest(tmp_path / "web.json", [{"name": "kick"}])
    output = tmp_path / "desktop.json"
    with pytest.raises(SystemExit) as result:
        app.main(
            [
                "--import-web-manifest",
                str(source),
                "--sample-audio-dir",
                str(tmp_path),
                "--sample-manifest-output",
                str(output),
            ]
        )
    assert result.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize(
    "args", [["--import-web-manifest", "web.json"], ["--sample-audio-dir", "."]]
)
def test_incomplete_cli_arguments_are_rejected(args):
    with pytest.raises(SystemExit) as result:
        app.main(args)
    assert result.value.code == 2


def test_gui_import_merges_and_reports_errors_without_losing_samples(tmp_path, monkeypatch):
    from ko2_daw import gui

    view = gui.KO2DawApp.__new__(gui.KO2DawApp)
    view.sample_library = SampleLibrary()
    original = view.sample_library.add_wav(wav_file(tmp_path / "original.wav"))
    source = manifest(tmp_path / "web.json", [{"name": "kick"}])
    wav_file(tmp_path / "kick.wav")
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **_: str(source))
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **_: str(tmp_path))
    actions, errors, refreshes = [], [], []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args: errors.append(args))
    view._set_action = actions.append
    view._refresh_sample_tree = lambda: refreshes.append(True)
    view._import_web_library()
    assert actions == ["imported 1 web library sample(s)"]
    assert refreshes == [True]
    assert view.sample_library.samples[0] == original
    # A retry must report the duplicate without discarding either sample.
    view._import_web_library()
    assert len(errors) == 1
    assert "Duplicate WAV" in errors[0][1]
    assert len(view.sample_library.samples) == 2
    assert refreshes == [True]


def test_gui_cancel_does_not_prompt_for_audio_or_change_library(monkeypatch):
    from ko2_daw import gui

    view = gui.KO2DawApp.__new__(gui.KO2DawApp)
    view.sample_library = SampleLibrary()
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **_: "")
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **_: pytest.fail("Cancelled"))
    view._import_web_library()
    assert not view.sample_library.samples
