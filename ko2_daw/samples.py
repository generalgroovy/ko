"""Local sample library helpers for the KO II companion workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
import tempfile
import wave


MAX_SAMPLE_SLOTS = 999


@dataclass(frozen=True)
class LocalSample:
    slot: int
    path: str
    name: str
    duration_sec: float
    sample_rate: int
    channels: int
    sample_width_bits: int
    frames: int
    size_bytes: int

    @property
    def pad_label(self) -> str:
        return f"{self.slot:03d}"


class SampleLibrary:
    """A manifest-backed local sample table with KO II-style 999 slot awareness."""

    def __init__(self, samples: list[LocalSample] | None = None):
        self.samples: dict[int, LocalSample] = {}
        for sample in samples or []:
            self.add(sample)

    def add_wav(self, path: str | Path, slot: int | None = None) -> LocalSample:
        sample = read_wav_metadata(path, self.next_free_slot() if slot is None else slot)
        self.add(sample)
        return sample

    def add(self, sample: LocalSample) -> None:
        _validate_slot(sample.slot)
        self.samples[sample.slot] = sample

    def next_free_slot(self) -> int:
        for slot in range(MAX_SAMPLE_SLOTS):
            if slot not in self.samples:
                return slot
        raise ValueError("No free sample slots remain.")

    def ordered(self) -> list[LocalSample]:
        return [self.samples[slot] for slot in sorted(self.samples)]

    def to_manifest(self) -> dict[str, object]:
        return {
            "schema": "ko2-sampler-daw.sample-manifest.v1",
            "slot_count": MAX_SAMPLE_SLOTS,
            "samples": [asdict(sample) for sample in self.ordered()],
        }

    def save(self, path: str | Path) -> Path:
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_manifest(), indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent) as handle:
            handle.write(payload)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(target)
        return target

    @classmethod
    def load(cls, path: str | Path) -> "SampleLibrary":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([LocalSample(**sample) for sample in data.get("samples", [])])


def read_wav_metadata(path: str | Path, slot: int) -> LocalSample:
    _validate_slot(slot)
    source = Path(path).resolve()
    if source.suffix.lower() != ".wav":
        raise ValueError("Only WAV import is supported without third-party audio decoders.")
    with wave.open(str(source), "rb") as handle:
        sample_rate = handle.getframerate()
        frames = handle.getnframes()
        channels = handle.getnchannels()
        sample_width_bits = handle.getsampwidth() * 8
    duration = frames / sample_rate if sample_rate else 0.0
    return LocalSample(
        slot=slot,
        path=str(source),
        name=source.stem,
        duration_sec=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bits=sample_width_bits,
        frames=frames,
        size_bytes=source.stat().st_size,
    )


def play_wav(path: str | Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Local WAV preview uses winsound and is available on Windows.")
    import winsound

    winsound.PlaySound(str(Path(path)), winsound.SND_FILENAME | winsound.SND_ASYNC)


def stop_wav() -> None:
    if sys.platform != "win32":
        return
    import winsound

    winsound.PlaySound(None, winsound.SND_PURGE)


def _validate_slot(slot: int) -> None:
    if not 0 <= slot < MAX_SAMPLE_SLOTS:
        raise ValueError(f"Sample slot must be between 0 and {MAX_SAMPLE_SLOTS - 1}.")
