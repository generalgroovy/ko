"""Tests for the non-destructive audio timeline and render engine."""

from __future__ import annotations

import math
from pathlib import Path
import struct
import wave

import pytest

from ko2_daw.app import main
from ko2_daw.audio_timeline import (
    AudioSession,
    default_audio_project,
    read_wave_source,
    render_audio_project,
    waveform_peaks,
)


def _tone(
    path: Path,
    *,
    frequency: float = 500.0,
    duration: float = 0.2,
    sample_rate: int = 8000,
    amplitude: float = 0.5,
) -> Path:
    frames = round(duration * sample_rate)
    payload = bytearray()
    for index in range(frames):
        value = round(math.sin(index * frequency * math.tau / sample_rate) * amplitude * 32767)
        payload.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(payload)
    return path


def test_import_edit_split_undo_redo_and_persistence(tmp_path) -> None:
    source = _tone(tmp_path / "tone.wav")
    session = AudioSession(default_audio_project(2))
    clip = session.import_wav(source, track_id="T02", start_sec=1.0)
    session.set_clip(
        clip.clip_id,
        source_in_sec=0.02,
        source_out_sec=0.18,
        stretch=2,
        gain_db=-3,
        pan=0.25,
        fade_in_sec=0.02,
        fade_out_sec=0.02,
    )

    left, right = session.split_clip(clip.clip_id, 1.16)

    assert left.end_sec == pytest.approx(1.16)
    assert right.start_sec == pytest.approx(1.16)
    assert len(session.project.clips) == 2
    assert session.undo()
    assert len(session.project.clips) == 1
    assert session.redo()
    assert len(session.project.clips) == 2

    path = session.save(tmp_path / "audio-project.json")
    loaded = AudioSession.load(path)
    assert loaded.project.to_dict() == session.project.to_dict()


def test_render_mix_resamples_stretches_fades_and_writes_stereo(tmp_path) -> None:
    source = _tone(tmp_path / "tone.wav", duration=0.1, sample_rate=8000)
    session = AudioSession(default_audio_project(1))
    session.project.sample_rate = 16000
    clip = session.import_wav(source)
    session.set_clip(
        clip.clip_id,
        stretch=2,
        fade_in_sec=0.02,
        fade_out_sec=0.02,
    )

    result = render_audio_project(session.project, tmp_path / "mix.wav")

    assert result.frames == 3200
    assert result.duration_sec == pytest.approx(0.2)
    assert 0 < result.peak < 1
    assert result.clipped_samples == 0
    with wave.open(str(result.path), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 3200


def test_track_solo_mute_and_normalized_render(tmp_path) -> None:
    source = _tone(tmp_path / "tone.wav", amplitude=0.9)
    session = AudioSession(default_audio_project(2))
    session.project.sample_rate = 8000
    first = session.import_wav(source, track_id="T01")
    session.import_wav(source, track_id="T02")
    session.set_track("T02", solo=True)
    session.set_clip(first.clip_id, gain_db=18)

    result = render_audio_project(
        session.project,
        tmp_path / "normalized.wav",
        normalize=True,
    )

    assert result.clipped_samples == 0
    assert result.peak <= 1
    assert result.normalized_gain_db > -0.5


def test_waveform_peaks_and_reverse(tmp_path) -> None:
    source = _tone(tmp_path / "tone.wav")
    session = AudioSession(default_audio_project(1))
    clip = session.import_wav(source)

    normal = waveform_peaks(clip, points=10)
    session.set_clip(clip.clip_id, reverse=True)
    reversed_peaks = waveform_peaks(clip, points=10)

    assert len(normal) == 10
    assert reversed_peaks == list(reversed(normal))


def test_rejects_non_wav_and_overlapping_fades(tmp_path) -> None:
    invalid = tmp_path / "sound.mp3"
    invalid.write_bytes(b"not audio")
    with pytest.raises(ValueError, match="PCM WAV"):
        read_wave_source(invalid)

    source = _tone(tmp_path / "tone.wav")
    session = AudioSession(default_audio_project(1))
    clip = session.import_wav(source)
    before = session.project.to_dict()
    with pytest.raises(ValueError, match="fades"):
        session.set_clip(clip.clip_id, fade_in_sec=0.2, fade_out_sec=0.2)
    assert session.project.to_dict() == before
    with pytest.raises(ValueError, match="pan"):
        session.set_track("T01", pan=2)
    assert session.project.to_dict() == before


def test_audio_render_cli(tmp_path, capsys) -> None:
    source = _tone(tmp_path / "tone.wav")
    session = AudioSession(default_audio_project(1))
    session.project.sample_rate = 8000
    session.import_wav(source)
    project = session.save(tmp_path / "project.json")
    output = tmp_path / "render.wav"

    result = main(
        [
            "--audio-render-project",
            str(project),
            "--audio-render-output",
            str(output),
            "--audio-normalize",
        ]
    )
    text = capsys.readouterr().out

    assert result == 0
    assert output.exists()
    assert f"audio_render={output.resolve()}" in text
    assert "audio_render_clipped=0" in text
