"""Read-only EP-133 device inventory with integrity metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Callable

from ko2_daw.config import DAWConfig, DeviceSafetyConfig
from ko2_daw.controller import DAWController
from ko2_daw.io_utils import atomic_write_text
from ko2_daw.midi import MidiMessage, WinMMInputMonitor, WinMMMidiBackend, midi_capability_report
from ko2_daw.routing import KO2Route, resolve_ko2_route
from ko2_daw.sysex_exchange import (
    SysexDecodedResponse,
    decode_sysex_response,
    matching_sysex_responses,
)
from ko2_daw.te_sysex import (
    TEFileCommand,
    build_file_init_payload,
    build_file_list_payload,
    build_te_frame,
    build_universal_identity_request,
)


SnapshotExchange = Callable[[bytes, float], list[SysexDecodedResponse]]


@dataclass(frozen=True)
class SnapshotLimits:
    pages_per_directory: int = 32
    max_depth: int = 8
    max_directories: int = 1000
    timeout_sec: float = 2.0

    def validate(self) -> None:
        if not 1 <= self.pages_per_directory <= 256:
            raise ValueError("pages_per_directory must be between 1 and 256.")
        if not 0 <= self.max_depth <= 32:
            raise ValueError("max_depth must be between 0 and 32.")
        if not 1 <= self.max_directories <= 10000:
            raise ValueError("max_directories must be between 1 and 10000.")
        if not 0.2 <= self.timeout_sec <= 30:
            raise ValueError("timeout_sec must be between 0.2 and 30.")


@dataclass(frozen=True)
class DeviceFileRecord:
    node_id: int
    parent_node_id: int
    path: str
    name: str
    kind: str
    size: int
    depth: int
    page: int


@dataclass
class DeviceSnapshot:
    generated_at: str
    route_status: str
    input_port: str
    output_port: str
    identity_sku: str = ""
    chunk_size: int = 0
    records: list[DeviceFileRecord] = field(default_factory=list)
    directories_scanned: int = 0
    pages_requested: int = 0
    warnings: list[str] = field(default_factory=list)
    integrity_sha256: str = ""

    @property
    def files(self) -> list[DeviceFileRecord]:
        return [record for record in self.records if record.kind == "file"]

    @property
    def directories(self) -> list[DeviceFileRecord]:
        return [record for record in self.records if record.kind == "dir"]

    @property
    def total_file_bytes(self) -> int:
        return sum(record.size for record in self.files)

    def finalize(self) -> None:
        canonical = [
            asdict(record)
            for record in sorted(self.records, key=lambda item: (item.path, item.node_id))
        ]
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.integrity_sha256 = hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "route": {
                "status": self.route_status,
                "input_port": self.input_port,
                "output_port": self.output_port,
            },
            "device": {
                "identity_sku": self.identity_sku,
                "chunk_size": self.chunk_size,
            },
            "summary": {
                "records": len(self.records),
                "files": len(self.files),
                "directories": len(self.directories),
                "directories_scanned": self.directories_scanned,
                "pages_requested": self.pages_requested,
                "total_file_bytes": self.total_file_bytes,
                "integrity_sha256": self.integrity_sha256,
            },
            "warnings": list(self.warnings),
            "records": [asdict(record) for record in self.records],
        }


class ReadOnlySysexSession:
    """Persistent WinMM input/output session for sequential read-only probes."""

    def __init__(self, input_port: str, output_port: str, *, max_sysex_bytes: int = 4 * 1024 * 1024):
        self.input_port = input_port
        self.output_port = output_port
        self._responses: list[bytes] = []
        self._lock = threading.Lock()
        self._received = threading.Event()
        self._backend = WinMMMidiBackend()
        safety = DeviceSafetyConfig(
            dry_run=False,
            allowed_output_ports=(output_port,),
            sysex_enabled=True,
            max_sysex_bytes=max_sysex_bytes,
        )
        self._controller = DAWController(
            config=DAWConfig(safety=safety),
            backend=self._backend,
            output_port=output_port,
        )
        self._monitor = WinMMInputMonitor(
            input_port,
            self._observe,
            include_sysex=True,
            sysex_buffer_size=max_sysex_bytes,
        )
        self._started = False

    def _observe(self, message: MidiMessage) -> None:
        if message.kind != "sysex" or not message.data:
            return
        with self._lock:
            self._responses.append(message.data)
        self._received.set()

    def start(self) -> None:
        if not self._started:
            self._monitor.start()
            self._started = True

    def send(self, frame: bytes, timeout_sec: float) -> list[SysexDecodedResponse]:
        return [decode_sysex_response(response) for response in self.send_raw(frame, timeout_sec)]

    def send_raw(self, frame: bytes, timeout_sec: float) -> list[bytes]:
        self.start()
        with self._lock:
            self._responses.clear()
        self._received.clear()
        self._controller.send(MidiMessage.sysex(frame))
        deadline = time.monotonic() + max(0.1, timeout_sec)
        cursor = 0
        collected: list[bytes] = []
        while time.monotonic() < deadline:
            with self._lock:
                responses = list(self._responses[cursor:])
                cursor = len(self._responses)
            collected.extend(responses)
            if matching_sysex_responses(frame, responses):
                return collected
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._received.wait(min(remaining, 0.05))
            self._received.clear()
        return collected

    def close(self) -> None:
        if self._started:
            self._monitor.stop()
            self._started = False
        self._backend.close()

    def __enter__(self) -> "ReadOnlySysexSession":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


def capture_device_snapshot(
    *,
    limits: SnapshotLimits | None = None,
    midi_report: dict[str, object] | None = None,
    route: KO2Route | None = None,
    exchange: SnapshotExchange | None = None,
) -> DeviceSnapshot:
    """Capture the complete visible file tree without sending write commands."""

    scan_limits = limits or SnapshotLimits()
    scan_limits.validate()
    report = midi_report or midi_capability_report()
    resolved_route = route or resolve_ko2_route(report, "usb-midi")
    if not resolved_route.input_port or not resolved_route.output_port:
        raise RuntimeError("A visible EP-133 MIDI input and output are required for a snapshot.")

    snapshot = DeviceSnapshot(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        route_status=resolved_route.status,
        input_port=resolved_route.input_port,
        output_port=resolved_route.output_port,
    )

    owned_session: ReadOnlySysexSession | None = None
    if exchange is None:
        owned_session = ReadOnlySysexSession(resolved_route.input_port, resolved_route.output_port)
        owned_session.start()
        exchange = owned_session.send

    try:
        _capture_identity_and_init(snapshot, exchange, scan_limits.timeout_sec)
        _capture_file_tree(snapshot, exchange, scan_limits)
        snapshot.finalize()
        return snapshot
    finally:
        if owned_session is not None:
            owned_session.close()


def save_device_snapshot(snapshot: DeviceSnapshot, path: str | Path) -> Path:
    if not snapshot.integrity_sha256:
        snapshot.finalize()
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n"
    return atomic_write_text(path, payload)


def _capture_identity_and_init(
    snapshot: DeviceSnapshot,
    exchange: SnapshotExchange,
    timeout_sec: float,
) -> None:
    identity = exchange(build_universal_identity_request(), timeout_sec)
    for response in identity:
        sku = response.details.get("sku")
        if sku:
            snapshot.identity_sku = str(sku)
            break
    if not snapshot.identity_sku:
        snapshot.warnings.append("Universal identity request returned no recognized SKU.")

    init = exchange(
        build_te_frame(TEFileCommand.COMMAND, build_file_init_payload(), request_id=1),
        timeout_sec,
    )
    for response in init:
        chunk_size = response.details.get("chunk_size")
        if chunk_size:
            snapshot.chunk_size = int(chunk_size)
            break
    if not snapshot.chunk_size:
        snapshot.warnings.append("File protocol initialization returned no chunk size.")


def _capture_file_tree(
    snapshot: DeviceSnapshot,
    exchange: SnapshotExchange,
    limits: SnapshotLimits,
) -> None:
    pending: list[tuple[int, str, int]] = [(0, "/", 0)]
    seen_directories: set[int] = set()
    seen_records: set[tuple[int, str]] = set()
    request_id = 2

    while pending and snapshot.directories_scanned < limits.max_directories:
        node_id, parent_path, depth = pending.pop(0)
        if node_id in seen_directories or depth > limits.max_depth:
            continue
        seen_directories.add(node_id)
        snapshot.directories_scanned += 1
        page_signatures: set[tuple[tuple[object, ...], ...]] = set()

        for page in range(limits.pages_per_directory):
            request_id = (request_id + 1) & 0x3FFF or 1
            frame = build_te_frame(
                TEFileCommand.COMMAND,
                build_file_list_payload(node_id, page),
                request_id=request_id,
            )
            responses = exchange(frame, limits.timeout_sec)
            snapshot.pages_requested += 1
            entries = _entries_from_responses(responses)
            if not entries:
                break
            signature = tuple(
                (
                    entry.get("node_id"),
                    entry.get("kind"),
                    entry.get("name"),
                    entry.get("size"),
                )
                for entry in entries
            )
            if signature in page_signatures:
                snapshot.warnings.append(f"Repeated page detected at node {node_id}, page {page}; scan stopped for this node.")
                break
            page_signatures.add(signature)

            for entry in entries:
                child_node = int(entry.get("node_id") or 0)
                name = str(entry.get("name") or child_node)
                kind = str(entry.get("kind") or "file")
                size = int(entry.get("size") or 0)
                path = _child_path(parent_path, name)
                key = (child_node, path)
                if key in seen_records:
                    continue
                seen_records.add(key)
                snapshot.records.append(
                    DeviceFileRecord(
                        node_id=child_node,
                        parent_node_id=node_id,
                        path=path,
                        name=name,
                        kind=kind,
                        size=size,
                        depth=depth,
                        page=page,
                    )
                )
                if kind == "dir" and child_node not in seen_directories:
                    pending.append((child_node, path, depth + 1))

    if pending:
        snapshot.warnings.append(
            f"Directory limit reached at {limits.max_directories}; {len(pending)} directories were not scanned."
        )


def _entries_from_responses(responses: list[SysexDecodedResponse]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for response in responses:
        response_entries = response.details.get("entries")
        if isinstance(response_entries, list):
            entries.extend(entry for entry in response_entries if isinstance(entry, dict))
    return entries


def _child_path(parent_path: str, name: str) -> str:
    cleaned = str(name).strip("/")
    if parent_path == "/":
        return f"/{cleaned}"
    return f"{parent_path.rstrip('/')}/{cleaned}"
