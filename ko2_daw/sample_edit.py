"""Bounded-memory PCM waveform inspection and non-destructive sample trimming."""

from __future__ import annotations

import math
import wave
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path


class EditCancelled(ValueError):
    """A requested background edit stopped without keeping partial output."""


def _check_cancel(cancel: Callable[[], bool] | None) -> None:
    if cancel and cancel():
        raise EditCancelled("Cancelled. The original is unchanged.")


def selection_frames(start: float, end: float, rate: int, frames: int) -> tuple[int, int]:
    """Validate seconds and resolve the same exact frame boundaries used on export."""
    if rate <= 0:
        raise ValueError("The sample rate must be positive.")
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("Start and end must be finite seconds.")
    if not 0 <= start < end <= frames / rate:
        raise ValueError("Choose a start before the end, within the sample duration.")
    first, last = round(start * rate), min(frames, round(end * rate))
    if first >= last:
        raise ValueError("The selection must contain at least one audio frame.")
    return first, last


def slice_boundaries(first: int, last: int, count: int) -> list[tuple[int, int]]:
    """Even frame partitions: every selected frame appears once, in source order."""
    if count not in (1, 2, 4, 8, 16):
        raise ValueError("Choose 1, 2, 4, 8 or 16 copies.")
    if first < 0 or last - first < count:
        raise ValueError("Each slice needs at least one audio frame.")
    edges = [first + (last - first) * index // count for index in range(count + 1)]
    return list(pairwise(edges))


def waveform(
    path: str | Path, bins: int = 360, *, cancel: Callable[[], bool] | None = None
) -> tuple[float, list[tuple[float, float]]]:
    """Return duration and channel-combined extrema, retaining short transients."""
    if not 1 <= bins <= 4096:
        raise ValueError("Waveform resolution must be between 1 and 4096.")
    with wave.open(str(path), "rb") as source:
        frames, rate = source.getnframes(), source.getframerate()
        width, channels = source.getsampwidth(), source.getnchannels()
        if rate <= 0:
            raise ValueError("The sample rate must be positive.")
        if not frames:
            raise ValueError("The sample contains no audio frames.")
        peaks = [[0.0, 0.0] for _ in range(min(bins, frames))]
        count = 0
        scale = float(1 << (width * 8 - 1))
        while raw := source.readframes(4096):
            _check_cancel(cancel)
            frame_width = width * channels
            if len(raw) % frame_width:
                raise ValueError("The WAV is incomplete; an audio frame is truncated.")
            for offset in range(0, len(raw), frame_width):
                bucket = min(len(peaks) - 1, count * len(peaks) // frames)
                for channel in range(channels):
                    start = offset + channel * width
                    value = int.from_bytes(raw[start : start + width], "little", signed=width != 1)
                    level = (value - 128 if width == 1 else value) / scale
                    peaks[bucket][0] = min(peaks[bucket][0], level)
                    peaks[bucket][1] = max(peaks[bucket][1], level)
                count += 1
        if count != frames:
            raise ValueError("The WAV is incomplete; its audio is shorter than its header.")
        return frames / rate, [(low, high) for low, high in peaks]


def _write_region(source, target: Path, first: int, last: int, cancel) -> None:
    _check_cancel(cancel)
    source.setpos(first)
    with target.open("xb") as output:
        try:
            with wave.open(output, "wb") as writer:
                writer.setparams(source.getparams())
                remaining = last - first
                frame_width = source.getsampwidth() * source.getnchannels()
                while remaining:
                    _check_cancel(cancel)
                    raw = source.readframes(min(remaining, 65536))
                    if not raw or len(raw) % frame_width:
                        raise ValueError("The source WAV is incomplete.")
                    writer.writeframesraw(raw)
                    remaining -= len(raw) // frame_width
            _check_cancel(cancel)
        except BaseException:
            output.close()
            target.unlink(missing_ok=True)
            raise


def trim_copy(
    source_path: str | Path,
    target_path: str | Path,
    start: float,
    end: float,
    *,
    cancel: Callable[[], bool] | None = None,
) -> Path:
    """Copy [start, end) to a new WAV; never replace any existing file."""
    source_path, target = Path(source_path).resolve(), Path(target_path).resolve()
    if source_path == target:
        raise ValueError("Choose a new file; the original sample is preserved.")
    with wave.open(str(source_path), "rb") as source:
        rate, frames = source.getframerate(), source.getnframes()
        first, last = selection_frames(start, end, rate, frames)
        # Exclusive creation also protects against a destination appearing after the dialog.
        _write_region(source, target, first, last, cancel)
    return target


def slice_copies(
    source_path: str | Path,
    target_folder: str | Path,
    start: float,
    end: float,
    count: int,
    *,
    cancel: Callable[[], bool] | None = None,
) -> list[Path]:
    """Export equal slices to an exclusively new folder, removing owned output on failure.

    No resampling, fades or zero-crossing shifts: concatenated PCM equals the selection.
    Cleanup never recursively removes unrelated files that another process might add.
    """
    source_path, folder = Path(source_path).resolve(), Path(target_folder).resolve()
    completed: list[Path] = []
    with wave.open(str(source_path), "rb") as source:
        first, last = selection_frames(start, end, source.getframerate(), source.getnframes())
        regions = slice_boundaries(first, last, count)
        _check_cancel(cancel)
        folder.mkdir()
        try:
            for index, (first, last) in enumerate(regions, start=1):
                target = folder / f"slice-{index:02d}.wav"
                _write_region(source, target, first, last, cancel)
                completed.append(target)
            _check_cancel(cancel)
        except BaseException:
            for target in completed:
                target.unlink(missing_ok=True)
            # Leave a folder containing unexpected files intact.
            if not any(folder.iterdir()):
                folder.rmdir()
            raise
    return completed
