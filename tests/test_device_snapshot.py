"""Tests for the read-only EP-133 device snapshot engine."""

from __future__ import annotations

import json

from ko2_daw.device_snapshot import (
    SnapshotLimits,
    capture_device_snapshot,
    save_device_snapshot,
)
from ko2_daw.routing import KO2Route
from ko2_daw.sysex_exchange import SysexDecodedResponse
from ko2_daw.te_sysex import TEFileCommand, parse_te_frame


def _fake_route() -> KO2Route:
    return KO2Route(
        status="usb-midi-ready",
        input_port="EP-133",
        output_port="EP-133",
        allow_output="EP-133",
        message="test route",
    )


def _fake_exchange(frame: bytes, _timeout: float) -> list[SysexDecodedResponse]:
    if frame[:5] == bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01]):
        return [SysexDecodedResponse("identity", "TE identity TE032AS001", "", {"sku": "TE032AS001"})]

    parsed = parse_te_frame(frame)
    assert parsed is not None
    payload = parsed.payload
    if payload[0] == TEFileCommand.INIT:
        return [SysexDecodedResponse("te", "file init chunk 512 bytes", "", {"chunk_size": 512})]
    if payload[0] != TEFileCommand.LIST:
        return []

    page = (payload[1] << 8) | payload[2]
    node_id = (payload[3] << 8) | payload[4]
    entries: dict[tuple[int, int], list[dict[str, object]]] = {
        (0, 0): [
            {"node_id": 1000, "name": "sounds", "size": 0, "kind": "dir"},
            {"node_id": 2000, "name": "projects", "size": 0, "kind": "dir"},
        ],
        (1000, 0): [
            {"node_id": 1, "name": "001.pcm", "size": 1200, "kind": "file"},
            {"node_id": 2, "name": "002.pcm", "size": 800, "kind": "file"},
        ],
        (2000, 0): [
            {"node_id": 3000, "name": "01", "size": 0, "kind": "dir"},
        ],
        (3000, 0): [
            {"node_id": 3001, "name": "pattern.json", "size": 400, "kind": "file"},
        ],
    }
    page_entries = entries.get((node_id, page), [])
    if not page_entries:
        return []
    return [
        SysexDecodedResponse(
            "te",
            f"file list {len(page_entries)} entries",
            "",
            {"page": page, "entries": page_entries},
        )
    ]


def test_capture_device_snapshot_builds_tree_and_integrity_hash() -> None:
    snapshot = capture_device_snapshot(
        limits=SnapshotLimits(pages_per_directory=4, max_depth=4, max_directories=20),
        midi_report={},
        route=_fake_route(),
        exchange=_fake_exchange,
    )

    assert snapshot.identity_sku == "TE032AS001"
    assert snapshot.chunk_size == 512
    assert snapshot.directories_scanned == 4
    assert len(snapshot.records) == 6
    assert len(snapshot.files) == 3
    assert len(snapshot.directories) == 3
    assert snapshot.total_file_bytes == 2400
    assert len(snapshot.integrity_sha256) == 64
    assert {record.path for record in snapshot.records} == {
        "/sounds",
        "/projects",
        "/sounds/001.pcm",
        "/sounds/002.pcm",
        "/projects/01",
        "/projects/01/pattern.json",
    }


def test_device_snapshot_save_round_trip(tmp_path) -> None:
    snapshot = capture_device_snapshot(
        route=_fake_route(),
        midi_report={},
        exchange=_fake_exchange,
    )
    path = save_device_snapshot(snapshot, tmp_path / "snapshot.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["device"]["identity_sku"] == "TE032AS001"
    assert payload["summary"]["files"] == 3
    assert payload["summary"]["integrity_sha256"] == snapshot.integrity_sha256


def test_snapshot_limits_validate_ranges() -> None:
    try:
        SnapshotLimits(pages_per_directory=0).validate()
    except ValueError as exc:
        assert "pages_per_directory" in str(exc)
    else:
        raise AssertionError("invalid limits should fail")
