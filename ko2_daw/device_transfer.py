"""Integrity-checked, read-only EP-133 file and metadata downloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import re
import struct
from typing import Callable
import wave
import zlib

from ko2_daw.device_snapshot import ReadOnlySysexSession
from ko2_daw.io_utils import atomic_write_bytes, atomic_write_text
from ko2_daw.midi import midi_capability_report
from ko2_daw.project_archive import inspect_project_archive
from ko2_daw.routing import KO2Route, resolve_ko2_route
from ko2_daw.sysex_exchange import matching_sysex_responses
from ko2_daw.te_sysex import (
    TEFileCommand,
    TEFileDownloadInfo,
    TEFrame,
    TE_ID,
    build_file_get_data_payload,
    build_file_get_init_payload,
    build_file_init_payload,
    build_file_metadata_get_payload,
    build_te_frame,
    parse_file_get_data_response,
    parse_file_get_init_response,
    parse_file_init_response,
    parse_te_frame,
)


RawExchange = Callable[[bytes, float], list[bytes]]
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class DeviceDownloadLimits:
    timeout_sec: float = 3.0
    max_file_bytes: int = 128 * 1024 * 1024
    max_pages: int = 65536
    max_metadata_pages: int = 128
    max_metadata_bytes: int = 1024 * 1024

    def validate(self) -> None:
        if not 0.2 <= self.timeout_sec <= 30:
            raise ValueError("timeout_sec must be between 0.2 and 30.")
        if not 1 <= self.max_file_bytes <= 1024 * 1024 * 1024:
            raise ValueError("max_file_bytes must be between 1 byte and 1 GiB.")
        if not 1 <= self.max_pages <= 65536:
            raise ValueError("max_pages must be between 1 and 65536.")
        if not 1 <= self.max_metadata_pages <= 65536:
            raise ValueError("max_metadata_pages must be between 1 and 65536.")
        if not 1 <= self.max_metadata_bytes <= 16 * 1024 * 1024:
            raise ValueError("max_metadata_bytes must be between 1 byte and 16 MiB.")


@dataclass(frozen=True)
class DeviceFileDownload:
    node_id: int
    file_name: str
    flags: int
    declared_size: int
    offset: int
    chunk_size: int
    pages: int
    data: bytes = field(repr=False)
    metadata: dict[str, object] = field(default_factory=dict)
    metadata_text: str = ""
    sha256: str = ""
    crc32: int = 0
    metadata_crc32: int | None = None
    crc_matches_metadata: bool | None = None

    @property
    def downloaded_size(self) -> int:
        return len(self.data)

    @property
    def is_directory_archive(self) -> bool:
        return bool(self.flags & TEFileCommand.FILE_TYPE_DIR)


@dataclass(frozen=True)
class DeviceDownloadArtifact:
    bundle_dir: Path
    raw_path: Path
    manifest_path: Path
    metadata_path: Path
    latest_path: Path
    wav_path: Path | None = None
    project_analysis_path: Path | None = None


class DeviceFileClient:
    """Sequential TE file client limited to INIT, GET, and metadata GET."""

    def __init__(
        self,
        exchange: RawExchange,
        *,
        limits: DeviceDownloadLimits | None = None,
        request_id_start: int = 1000,
    ):
        self.exchange = exchange
        self.limits = limits or DeviceDownloadLimits()
        self.limits.validate()
        self.request_id = int(request_id_start) & 0x3FFF
        self.chunk_size = 0

    def initialize(self) -> int:
        frame = self._request(build_file_init_payload())
        parsed = parse_file_init_response(frame.payload)
        if not parsed or not parsed["chunk_size"]:
            raise RuntimeError("EP-133 file initialization returned no chunk size.")
        self.chunk_size = int(parsed["chunk_size"])
        return self.chunk_size

    def get_info(self, node_id: int, *, offset: int = 0) -> TEFileDownloadInfo:
        frame = self._request(build_file_get_init_payload(node_id, offset=offset))
        info = parse_file_get_init_response(frame.payload)
        if info.node_id != int(node_id):
            raise RuntimeError(
                f"EP-133 returned file node {info.node_id}, expected {int(node_id)}."
            )
        return info

    def get_metadata(self, node_id: int) -> tuple[dict[str, object], str]:
        parts: list[bytes] = []
        total_bytes = 0
        for page in range(self.limits.max_metadata_pages):
            frame = self._request(build_file_metadata_get_payload(node_id, page))
            payload = frame.payload
            if len(payload) < 2:
                raise RuntimeError(f"Metadata page {page} was shorter than its page header.")
            returned_page = int.from_bytes(payload[:2], "big")
            if returned_page != page:
                raise RuntimeError(
                    f"Unexpected metadata page {returned_page}; expected {page}."
                )
            body = payload[2:]
            if not body:
                break
            nul_index = body.find(b"\x00")
            content = body if nul_index < 0 else body[:nul_index]
            total_bytes += len(content)
            if total_bytes > self.limits.max_metadata_bytes:
                raise RuntimeError("Device metadata exceeded the configured byte limit.")
            parts.append(content)
            if nul_index >= 0:
                break
        else:
            raise RuntimeError("Device metadata exceeded the configured page limit.")

        text = b"".join(parts).decode("utf-8")
        if not text:
            return {}, ""
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise RuntimeError("Device metadata JSON is not an object.")
        return parsed, text

    def download(
        self,
        node_id: int,
        *,
        offset: int = 0,
        include_metadata: bool = True,
        progress: ProgressCallback | None = None,
    ) -> DeviceFileDownload:
        if not self.chunk_size:
            self.initialize()
        info = self.get_info(node_id, offset=offset)
        remaining = info.size - int(offset)
        if remaining < 0:
            raise RuntimeError(
                f"Download offset {offset} is beyond the declared file size {info.size}."
            )
        if remaining > self.limits.max_file_bytes:
            raise RuntimeError(
                f"Device file is {remaining} bytes; configured limit is "
                f"{self.limits.max_file_bytes} bytes."
            )

        chunks: list[bytes] = []
        downloaded = 0
        pages = 0
        while downloaded < remaining:
            if pages >= self.limits.max_pages:
                raise RuntimeError("Device download exceeded the configured page limit.")
            frame = self._request(build_file_get_data_payload(pages))
            page = parse_file_get_data_response(frame.payload)
            if page.page != pages:
                raise RuntimeError(f"Unexpected file page {page.page}; expected {pages}.")
            if not page.data:
                raise RuntimeError(
                    f"Device returned an empty page after {downloaded} of {remaining} bytes."
                )
            if downloaded + len(page.data) > remaining:
                raise RuntimeError(
                    f"Device page {pages} exceeded declared file size "
                    f"({downloaded + len(page.data)} > {remaining})."
                )
            chunks.append(page.data)
            downloaded += len(page.data)
            pages += 1
            _notify_progress(progress, downloaded, remaining, "data")

        data = b"".join(chunks)
        if len(data) != remaining:
            raise RuntimeError(
                f"Downloaded {len(data)} bytes but device declared {remaining} bytes."
            )

        metadata: dict[str, object] = {}
        metadata_text = ""
        if include_metadata:
            metadata, metadata_text = self.get_metadata(node_id)
            _notify_progress(progress, downloaded, remaining, "metadata")

        crc32 = zlib.crc32(data) & 0xFFFFFFFF
        metadata_crc = _metadata_crc(metadata)
        crc_match = None if metadata_crc is None else crc32 == metadata_crc
        return DeviceFileDownload(
            node_id=int(node_id),
            file_name=info.name,
            flags=info.flags,
            declared_size=info.size,
            offset=int(offset),
            chunk_size=self.chunk_size,
            pages=pages,
            data=data,
            metadata=metadata,
            metadata_text=metadata_text,
            sha256=hashlib.sha256(data).hexdigest(),
            crc32=crc32,
            metadata_crc32=metadata_crc,
            crc_matches_metadata=crc_match,
        )

    def _request(self, payload: bytes) -> TEFrame:
        self.request_id = (self.request_id + 1) & 0x3FFF or 1
        request = build_te_frame(
            TEFileCommand.COMMAND,
            payload,
            request_id=self.request_id,
        )
        raw_responses = self.exchange(request, self.limits.timeout_sec)
        responses = matching_sysex_responses(request, raw_responses)
        if not responses:
            logs = _device_log_messages(raw_responses)
            if logs:
                raise RuntimeError(
                    "EP-133 emitted a firmware log instead of the requested file response: "
                    f"{logs[-1]}. Reconnect or power-cycle the device before retrying."
                )
            raise TimeoutError(
                f"No matching EP-133 SysEx response for request {self.request_id}."
            )
        frame = parse_te_frame(responses[0])
        if frame is None:
            raise RuntimeError("EP-133 returned an invalid TE SysEx frame.")
        if frame.status != 0:
            raise RuntimeError(
                f"EP-133 file request failed with status {frame.status} "
                f"({frame.status_text})."
            )
        return frame


def download_device_file_live(
    node_id: int,
    *,
    include_metadata: bool = True,
    limits: DeviceDownloadLimits | None = None,
    midi_report: dict[str, object] | None = None,
    route: KO2Route | None = None,
    progress: ProgressCallback | None = None,
) -> DeviceFileDownload:
    report = midi_report or midi_capability_report()
    resolved_route = route or resolve_ko2_route(report, "usb-midi")
    if not resolved_route.input_port or not resolved_route.output_port:
        raise RuntimeError("A visible EP-133 MIDI input and output are required for download.")
    with ReadOnlySysexSession(
        resolved_route.input_port,
        resolved_route.output_port,
    ) as session:
        client = DeviceFileClient(session.send_raw, limits=limits)
        return client.download(
            node_id,
            include_metadata=include_metadata,
            progress=progress,
        )


def save_device_download(
    download: DeviceFileDownload,
    root: str | Path,
    *,
    export_wav: bool = True,
) -> DeviceDownloadArtifact:
    """Save an immutable content-addressed bundle and an atomic latest pointer."""

    library_root = Path(root).resolve()
    safe_name = _safe_filename(download.file_name)
    stem = Path(safe_name).stem or f"node-{download.node_id}"
    slot_dir = library_root / f"{download.node_id:05d}_{_safe_component(stem)}"
    bundle_dir = slot_dir / download.sha256
    bundle_dir.mkdir(parents=True, exist_ok=True)

    raw_name = safe_name
    if download.is_directory_archive and not Path(raw_name).suffix:
        raw_name = f"{raw_name}.tar"
    raw_path = atomic_write_bytes(bundle_dir / raw_name, download.data)

    metadata_path = atomic_write_text(
        bundle_dir / "metadata.json",
        json.dumps(download.metadata, indent=2, sort_keys=True) + "\n",
    )

    wav_path: Path | None = None
    if export_wav and _metadata_is_pcm(download.metadata):
        wav_path = atomic_write_bytes(
            bundle_dir / f"{Path(safe_name).stem}.wav",
            pcm_to_wav_bytes(download.data, download.metadata),
        )

    project_analysis_path: Path | None = None
    if download.is_directory_archive:
        try:
            project_info = inspect_project_archive(download.data)
        except ValueError:
            project_info = None
        if project_info is not None:
            project_analysis_path = atomic_write_text(
                bundle_dir / "project_analysis.json",
                json.dumps(project_info.to_dict(), indent=2, sort_keys=True) + "\n",
            )

    manifest = {
        "schema": "ko2-daw.device-download.v1",
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "node_id": download.node_id,
        "file_name": download.file_name,
        "flags": download.flags,
        "declared_size": download.declared_size,
        "downloaded_size": download.downloaded_size,
        "offset": download.offset,
        "chunk_size": download.chunk_size,
        "pages": download.pages,
        "sha256": download.sha256,
        "crc32": download.crc32,
        "metadata_crc32": download.metadata_crc32,
        "crc_matches_metadata": download.crc_matches_metadata,
        "raw_file": raw_path.name,
        "wav_file": wav_path.name if wav_path else None,
        "metadata_file": metadata_path.name,
        "project_analysis_file": (
            project_analysis_path.name if project_analysis_path else None
        ),
    }
    manifest_path = atomic_write_text(
        bundle_dir / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    latest = {
        "schema": "ko2-daw.device-download-latest.v1",
        "node_id": download.node_id,
        "sha256": download.sha256,
        "bundle": download.sha256,
        "manifest": str(manifest_path.relative_to(slot_dir)),
    }
    latest_path = atomic_write_text(
        slot_dir / "latest.json",
        json.dumps(latest, indent=2, sort_keys=True) + "\n",
    )
    return DeviceDownloadArtifact(
        bundle_dir=bundle_dir,
        raw_path=raw_path,
        manifest_path=manifest_path,
        metadata_path=metadata_path,
        latest_path=latest_path,
        wav_path=wav_path,
        project_analysis_path=project_analysis_path,
    )


def find_latest_device_artifact(
    root: str | Path,
    node_id: int,
) -> DeviceDownloadArtifact | None:
    library_root = Path(root).resolve()
    candidates = sorted(library_root.glob(f"{int(node_id):05d}_*/latest.json"))
    if not candidates:
        return None
    latest_path = candidates[-1]
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    bundle_dir = latest_path.parent / str(latest["bundle"])
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wav_name = manifest.get("wav_file")
    project_analysis_name = manifest.get("project_analysis_file")
    return DeviceDownloadArtifact(
        bundle_dir=bundle_dir,
        raw_path=bundle_dir / str(manifest["raw_file"]),
        manifest_path=manifest_path,
        metadata_path=bundle_dir / str(manifest["metadata_file"]),
        latest_path=latest_path,
        wav_path=(bundle_dir / str(wav_name)) if wav_name else None,
        project_analysis_path=(
            bundle_dir / str(project_analysis_name)
            if project_analysis_name
            else None
        ),
    )


def pcm_to_wav_bytes(data: bytes, metadata: dict[str, object]) -> bytes:
    channels = int(metadata.get("channels") or 0)
    sample_rate = int(metadata.get("samplerate") or 0)
    sample_format = str(metadata.get("format") or "").casefold()
    widths = {
        "u8": 1,
        "s16": 2,
        "s16le": 2,
        "s24": 3,
        "s24le": 3,
        "s32": 4,
        "s32le": 4,
    }
    sample_width = widths.get(sample_format)
    if sample_width is None:
        raise ValueError(f"Unsupported EP-133 PCM format for WAV export: {sample_format!r}.")
    if not 1 <= channels <= 8:
        raise ValueError("PCM channel count must be between 1 and 8.")
    if not 3000 <= sample_rate <= 768000:
        raise ValueError("PCM sample rate must be between 3000 and 768000 Hz.")
    frame_width = channels * sample_width
    if len(data) % frame_width:
        raise ValueError(
            f"PCM byte count {len(data)} is not divisible by frame width {frame_width}."
        )
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(data)
    return output.getvalue()


def wav_peak_envelope(path: str | Path, points: int = 320) -> list[tuple[float, float]]:
    """Return normalized min/max peaks for drawing a compact waveform."""

    if points < 1:
        raise ValueError("points must be positive.")
    with wave.open(str(Path(path)), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frames = handle.getnframes()
        data = handle.readframes(frames)
    if not frames:
        return []
    samples = _decode_pcm_samples(data, sample_width)
    frame_values = [
        max(abs(value) for value in samples[index : index + channels])
        for index in range(0, len(samples), channels)
    ]
    bucket = max(1, (len(frame_values) + points - 1) // points)
    maximum = float((1 << (sample_width * 8 - 1)) - 1) if sample_width > 1 else 255.0
    result: list[tuple[float, float]] = []
    for offset in range(0, len(frame_values), bucket):
        values = frame_values[offset : offset + bucket]
        peak = min(1.0, max(values) / maximum)
        result.append((-peak, peak))
    return result[:points]


def _decode_pcm_samples(data: bytes, sample_width: int) -> list[int]:
    if sample_width == 1:
        return [value - 128 for value in data]
    if sample_width == 2:
        return list(struct.unpack(f"<{len(data) // 2}h", data))
    if sample_width == 3:
        values: list[int] = []
        for offset in range(0, len(data), 3):
            raw = int.from_bytes(data[offset : offset + 3], "little", signed=False)
            values.append(raw - (1 << 24) if raw & (1 << 23) else raw)
        return values
    if sample_width == 4:
        return list(struct.unpack(f"<{len(data) // 4}i", data))
    raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes.")


def _metadata_crc(metadata: dict[str, object]) -> int | None:
    value = metadata.get("crc")
    if value is None:
        return None
    try:
        return int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None


def _notify_progress(
    callback: ProgressCallback | None,
    done: int,
    total: int,
    stage: str,
) -> None:
    if callback is None:
        return
    try:
        callback(done, total, stage)
    except Exception:
        # UI/reporting failures must never abandon an active device GET transaction.
        return


def _metadata_is_pcm(metadata: dict[str, object]) -> bool:
    return bool(metadata.get("channels") and metadata.get("samplerate") and metadata.get("format"))


def _device_log_messages(responses: list[bytes]) -> list[str]:
    messages: list[str] = []
    prefix = bytes([0xF0, *TE_ID, 0x33, 0x33])
    for response in responses:
        if response.startswith(prefix) and response.endswith(bytes([0xF7])):
            text = response[len(prefix) : -1].decode("utf-8", errors="replace").strip()
            if text:
                messages.append(text)
    return messages


def _safe_filename(value: str) -> str:
    name = Path(str(value).replace("\\", "/")).name
    cleaned = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name).strip(" .")
    return cleaned or "device-file.bin"


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "device-file"
