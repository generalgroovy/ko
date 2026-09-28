"""Bounded-memory PCM waveform inspection and non-destructive sample trimming."""

from __future__ import annotations

import math
import wave
from pathlib import Path


def waveform(path: str | Path, bins: int = 360) -> tuple[float, list[tuple[float, float]]]:
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


def trim_copy(source_path: str | Path, target_path: str | Path, start: float, end: float) -> Path:
    """Copy [start, end) to a new WAV; never replace any existing file."""
    source_path, target = Path(source_path).resolve(), Path(target_path).resolve()
    if source_path == target:
        raise ValueError("Choose a new file; the original sample is preserved.")
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("Start and end must be finite seconds.")
    with wave.open(str(source_path), "rb") as source:
        rate, frames = source.getframerate(), source.getnframes()
        if rate <= 0:
            raise ValueError("The sample rate must be positive.")
        if not 0 <= start < end <= frames / rate:
            raise ValueError("Choose a start before the end, within the sample duration.")
        first, last = round(start * rate), min(frames, round(end * rate))
        if first >= last:
            raise ValueError("The selection must contain at least one audio frame.")
        source.setpos(first)
        # Exclusive creation also protects against a destination appearing after the dialog.
        with target.open("xb") as output:
            try:
                with wave.open(output, "wb") as writer:
                    writer.setparams(source.getparams())
                    remaining = last - first
                    frame_width = source.getsampwidth() * source.getnchannels()
                    while remaining:
                        raw = source.readframes(min(remaining, 65536))
                        if not raw or len(raw) % frame_width:
                            raise ValueError("The source WAV is incomplete.")
                        writer.writeframesraw(raw)
                        remaining -= len(raw) // frame_width
            except BaseException:
                output.close()
                target.unlink(missing_ok=True)
                raise
    return target
