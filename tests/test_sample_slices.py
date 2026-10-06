"""Exact PCM partitioning and failure recovery, without audio or MIDI devices."""

import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ko2_daw.sample_edit import EditCancelled, slice_boundaries, slice_copies, trim_copy, waveform
from ko2_daw.samples import MAX_SAMPLE_SLOTS, SampleLibrary


def make_wav(path, *, width=2, channels=2, frames=43, rate=11):
    raw = bytes(index % 256 for index in range(frames * width * channels))
    with wave.open(str(path), "wb") as writer:
        writer.setparams((channels, width, rate, frames, "NONE", "not compressed"))
        writer.writeframes(raw)
    return raw


@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("count", [2, 4, 8, 16])
def test_slices_partition_exact_selected_pcm(tmp_path, width, channels, count):
    source = tmp_path / "source.wav"
    raw = make_wav(source, width=width, channels=channels)
    original = source.read_bytes()
    paths = slice_copies(source, tmp_path / "slices", 3 / 11, 42 / 11, count)
    chunks, lengths = [], []
    for path in paths:
        with wave.open(str(path), "rb") as result:
            assert result.getparams()[:3] == (channels, width, 11)
            lengths.append(result.getnframes())
            chunks.append(result.readframes(100))
    assert b"".join(chunks) == raw[3 * width * channels : 42 * width * channels]
    assert max(lengths) - min(lengths) <= 1
    assert source.read_bytes() == original
    assert [path.name for path in paths] == [f"slice-{i:02d}.wav" for i in range(1, count + 1)]


def test_all_supported_partitions_cover_every_frame_once():
    for count in (1, 2, 4, 8, 16):
        for first in (0, 1, 71):
            for length in range(count, count + 100):
                parts = slice_boundaries(first, first + length, count)
                assert [i for a, b in parts for i in range(a, b)] == list(
                    range(first, first + length)
                )
                assert all(b > a for a, b in parts)


@pytest.mark.parametrize(
    "start,end,count", [(0, 1, 16), (0, 1, 3), (-1, 2, 2), (0, float("nan"), 2)]
)
def test_bad_slice_selection_leaves_no_folder(tmp_path, start, end, count):
    source, folder = tmp_path / "source.wav", tmp_path / "slices"
    make_wav(source)
    with pytest.raises(ValueError):
        slice_copies(source, folder, start, end, count)
    assert not folder.exists()


def test_existing_folder_is_never_changed(tmp_path):
    source, folder = tmp_path / "source.wav", tmp_path / "slices"
    make_wav(source)
    folder.mkdir()
    keep = folder / "slice-01.wav"
    keep.write_bytes(b"unrelated")
    with pytest.raises(FileExistsError):
        slice_copies(source, folder, 0, 3, 4)
    assert keep.read_bytes() == b"unrelated"
    assert list(folder.iterdir()) == [keep]


def test_truncated_late_slice_removes_completed_and_partial_output(tmp_path):
    source, folder = tmp_path / "source.wav", tmp_path / "slices"
    make_wav(source)
    source.write_bytes(source.read_bytes()[:-2])
    with pytest.raises(ValueError, match="incomplete"):
        slice_copies(source, folder, 0, 43 / 11, 4)
    assert not folder.exists()


@pytest.mark.parametrize("cancel_at", [1, 2, 5, 8, 13])
def test_cancellation_cleans_its_entire_batch(tmp_path, cancel_at):
    source, folder = tmp_path / "source.wav", tmp_path / "slices"
    make_wav(source)
    original = source.read_bytes()
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= cancel_at

    with pytest.raises(EditCancelled):
        slice_copies(source, folder, 0, 43 / 11, 4, cancel=cancel)
    assert not folder.exists()
    assert source.read_bytes() == original


def test_cleanup_preserves_unrelated_files_added_during_export(tmp_path):
    source, folder = tmp_path / "source.wav", tmp_path / "slices"
    make_wav(source)

    def cancel():
        if (folder / "slice-01.wav").exists():
            (folder / "keep.txt").write_text("keep", encoding="utf-8")
            return True
        return False

    with pytest.raises(EditCancelled):
        slice_copies(source, folder, 0, 3, 4, cancel=cancel)
    assert [path.name for path in folder.iterdir()] == ["keep.txt"]
    assert (folder / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_large_trim_and_waveform_check_cancel_between_chunks(tmp_path):
    source, target = tmp_path / "long.wav", tmp_path / "trim.wav"
    make_wav(source, frames=200000, rate=48000)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls == 3

    with pytest.raises(EditCancelled):
        trim_copy(source, target, 0, 4, cancel=cancel)
    assert not target.exists()
    calls = 0
    with pytest.raises(EditCancelled):
        waveform(source, cancel=cancel)


def test_library_batch_validates_before_mutating(tmp_path):
    source, broken = tmp_path / "good.wav", tmp_path / "broken.wav"
    make_wav(source)
    broken.write_bytes(b"not wav")
    library = SampleLibrary()
    library.add_wav(source, slot=5)
    before = dict(library.samples)
    with pytest.raises((wave.Error, EOFError)):
        library.add_wavs([source, broken])
    assert library.samples == before
    added = library.add_wavs([source, source])
    assert [sample.slot for sample in added] == [0, 1]
    assert library.samples[5] == before[5]


def test_library_full_keeps_all_previous_rows(tmp_path):
    source = tmp_path / "source.wav"
    make_wav(source)
    library = SampleLibrary()
    sample = library.add_wav(source)
    library.samples = dict.fromkeys(range(MAX_SAMPLE_SLOTS - 1), sample)
    before = dict(library.samples)
    with pytest.raises(ValueError, match="free sample slots"):
        library.add_wavs([source, source])
    assert library.samples == before


@pytest.mark.parametrize("rate", [44100, 48000, 96000, 192000])
def test_single_frame_round_trip_from_gui_seconds(tmp_path, rate):
    source, target = tmp_path / "source.wav", tmp_path / "one-frame.wav"
    raw = make_wav(source, frames=1001, rate=rate)
    trim_copy(source, target, float(str(799 / rate)), float(str(800 / rate)))
    with wave.open(str(target), "rb") as result:
        assert result.getnframes() == 1
        assert result.readframes(2) == raw[799 * 4 : 800 * 4]


@pytest.mark.parametrize("error", [EOFError("truncated header"), FileNotFoundError("missing copy")])
def test_saved_copy_library_errors_stay_in_ui_and_keep_files(tmp_path, monkeypatch, error):
    from ko2_daw.gui import KO2DawApp

    source = tmp_path / "source.wav"
    make_wav(source)
    original = source.read_bytes()
    library = Mock()
    library.add_wavs.side_effect = error
    view = SimpleNamespace(sample_library=library, _refresh_sample_tree=Mock())
    notice = Mock()
    monkeypatch.setattr("ko2_daw.gui.messagebox.showerror", notice)
    KO2DawApp._add_sample_copies(view, [source])
    assert "Library unchanged" in notice.call_args.args[1]
    assert source.read_bytes() == original
    view._refresh_sample_tree.assert_not_called()
