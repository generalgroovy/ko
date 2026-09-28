"""Local sample library helpers for the KO II companion workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import re
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

    def import_web_manifest(self, path: str | Path, audio_directory: str | Path) -> int:
        """Merge a Web MIDI Lab export using its separately exported local WAVs.

        Validate the entire batch before replacing any state. Browser metadata is
        descriptive only: timing and format always come from the actual WAV.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
            raise ValueError("Web manifest must contain a samples array.")
        if data.get("schema"):
            raise ValueError("Expected a Web MIDI Lab export, not a desktop manifest.")
        entries = data["samples"]
        free_slots = [slot for slot in range(MAX_SAMPLE_SLOTS) if slot not in self.samples]
        if len(entries) > len(free_slots):
            raise ValueError("Not enough free sample slots for this manifest.")
        root = Path(audio_directory).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Audio directory must be a folder containing exported WAVs.")
        imported = []
        seen_paths = {Path(sample.path).resolve() for sample in self.samples.values()}
        for index, (entry, slot) in enumerate(zip(entries, free_slots), start=1):
            if not isinstance(entry, dict):
                raise ValueError(f"Sample {index} must be an object.")
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Sample {index} must have a nonempty name.")
            # Match audio.js safeName used by the browser's WAV download button.
            filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
            filename = re.sub(r"\s+", " ", filename).strip() + ".wav"
            source = (root / filename).resolve()
            if not source.is_relative_to(root):
                raise ValueError(f"Sample {index} resolves outside the audio directory.")
            if source in seen_paths:
                raise ValueError(f"Duplicate WAV for sample {index}: {filename}")
            if not source.is_file():
                raise ValueError(f"Missing exported WAV for sample {index}: {filename}")
            sample = read_wav_metadata(source, slot)
            imported.append(replace(sample, name=name.strip()))
            seen_paths.add(source)
        self.samples.update({sample.slot: sample for sample in imported})
        return len(imported)

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
        source = Path(path).resolve()
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("schema") != "ko2-sampler-daw.sample-manifest.v1":
            raise ValueError("Choose a desktop sample manifest. Use IMPORT WEB LIBRARY for browser exports.")
        entries = data.get("samples")
        if not isinstance(entries, list) or len(entries) > MAX_SAMPLE_SLOTS:
            raise ValueError("Desktop manifest must contain at most 999 samples.")
        restored = cls()
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise ValueError(f"Sample {index} must be an object.")
            slot = entry.get("slot")
            _validate_slot(slot)
            if slot in restored.samples:
                raise ValueError(f"Duplicate sample slot: {slot}")
            name, filename = entry.get("name"), entry.get("path")
            if not isinstance(name, str) or not name.strip() or not isinstance(filename, str) or not filename.strip():
                raise ValueError(f"Sample {index} needs a name and WAV path.")
            audio = Path(filename)
            if not audio.is_absolute():
                audio = source.parent / audio
            # The WAV is authoritative; stale or edited format metadata cannot
            # create a misleading sample table. Build a new library atomically.
            sample = read_wav_metadata(audio, slot)
            restored.add(replace(sample, name=name))
        return restored


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
    if type(slot) is not int or not 0 <= slot < MAX_SAMPLE_SLOTS:
        raise ValueError(f"Sample slot must be between 0 and {MAX_SAMPLE_SLOTS - 1}.")
