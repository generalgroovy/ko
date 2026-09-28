"""Audio-level regressions for local sample editing, independent of MIDI hardware."""

import struct
import wave

import pytest

from ko2_daw.sample_edit import trim_copy, waveform


def write_sample(path, width=2, channels=2):
    values = [0, 100, -100, 200, -200, 300, -300, 400]
    raw = b"".join(
        (value + 128 if width == 1 else value).to_bytes(width, "little", signed=width != 1)
        for value in (values if width != 1 else [0, 10, -10, 20, -20, 30, -30, 40])
        for _ in range(channels)
    )
    with wave.open(str(path), "wb") as output:
        output.setparams((channels, width, 8, 0, "NONE", "not compressed"))
        output.writeframes(raw)
    return raw


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_copy_keeps_exact_pcm_frames_and_original(tmp_path, width):
    source, target = tmp_path / "source.wav", tmp_path / "copy.wav"
    raw = write_sample(source, width)
    original = source.read_bytes()
    trim_copy(source, target, 0.25, 0.75)
    with wave.open(str(target), "rb") as result:
        assert result.getparams()[:4] == (2, width, 8, 4)
        assert result.readframes(10) == raw[2 * width * 2 : 6 * width * 2]
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "start,end", [(-1, 1), (0, 2), (1, 0), (0, 0), (float("nan"), 1), (0, float("inf")), (0, 0.001)]
)
def test_invalid_selection_creates_no_file(tmp_path, start, end):
    source, target = tmp_path / "source.wav", tmp_path / "copy.wav"
    write_sample(source)
    with pytest.raises(ValueError):
        trim_copy(source, target, start, end)
    assert not target.exists()


def test_existing_destination_and_source_are_preserved(tmp_path):
    source, target = tmp_path / "source.wav", tmp_path / "copy.wav"
    write_sample(source)
    target.write_bytes(b"keep this")
    with pytest.raises(FileExistsError):
        trim_copy(source, target, 0, 0.5)
    with pytest.raises(ValueError):
        trim_copy(source, source, 0, 0.5)
    assert target.read_bytes() == b"keep this"


def test_waveform_retains_a_short_transient_and_both_channels(tmp_path):
    source = tmp_path / "transient.wav"
    with wave.open(str(source), "wb") as output:
        output.setparams((2, 2, 8, 0, "NONE", "not compressed"))
        output.writeframes(struct.pack("<16h", *([0, 0] * 3 + [-32768, 32767] + [0, 0] * 4)))
    duration, peaks = waveform(source, 2)
    assert duration == 1
    assert peaks[0] == (-1, 32767 / 32768)
    assert peaks[1] == (0, 0)


@pytest.mark.parametrize("missing", [1, 8])
def test_truncated_audio_cleans_partial_copy(tmp_path, missing):
    source, target = tmp_path / "source.wav", tmp_path / "copy.wav"
    write_sample(source)
    source.write_bytes(source.read_bytes()[:-missing])
    with pytest.raises(ValueError, match="incomplete"):
        trim_copy(source, target, 0, 1)
    assert not target.exists()
    with pytest.raises(ValueError, match="incomplete"):
        waveform(source)


def test_zero_sample_rate_is_reported(tmp_path):
    source = tmp_path / "source.wav"
    write_sample(source)
    raw = bytearray(source.read_bytes())
    raw[24:28] = b"\0" * 4
    source.write_bytes(raw)
    for operation in (
        lambda: waveform(source),
        lambda: trim_copy(source, tmp_path / "copy.wav", 0, 1),
    ):
        with pytest.raises(ValueError, match="rate"):
            operation()


def test_main_window_waits_for_sample_export(monkeypatch):
    from unittest.mock import Mock

    from ko2_daw.gui import KO2DawApp
    from ko2_daw.sample_editor import SampleEditor

    app = KO2DawApp.__new__(KO2DawApp)
    app.root = Mock()
    editor = SampleEditor.__new__(SampleEditor)
    editor.saving = True
    app.root.winfo_children.return_value = [editor]
    app._disconnect_live = Mock()
    notice = Mock()
    monkeypatch.setattr("ko2_daw.gui.messagebox.showinfo", notice)
    app._close()
    notice.assert_called_once()
    app.root.destroy.assert_not_called()
    app._disconnect_live.assert_not_called()
