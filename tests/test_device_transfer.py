"""Tests for read-only EP-133 file downloads and WAV export."""

from __future__ import annotations

import json
from pathlib import Path
import wave

from ko2_daw.app import main
from ko2_daw.device_transfer import (
    DeviceDownloadArtifact,
    DeviceDownloadLimits,
    DeviceFileDownload,
    DeviceFileClient,
    find_latest_device_artifact,
    pcm_to_wav_bytes,
    save_device_download,
)
from ko2_daw.gui_device_library import load_snapshot_sound_entries
from ko2_daw.sysex_exchange import sysex_response_matches
from ko2_daw.te_sysex import (
    BIT_REQUEST_ID_AVAILABLE,
    SYSEX_END,
    SYSEX_START,
    TEFileCommand,
    TE_ID,
    TE_MARKER,
    build_file_get_data_payload,
    build_file_get_init_payload,
    build_te_frame,
    pack_to_7bit_payload,
    parse_te_frame,
)


PCM_DATA = bytes(range(64)) * 8
METADATA = {
    "name": "test sound",
    "channels": 1,
    "samplerate": 46875,
    "format": "s16",
}


class FakeDeviceExchange:
    def __init__(self):
        self.requests: list[bytes] = []

    def __call__(self, request: bytes, _timeout: float) -> list[bytes]:
        self.requests.append(request)
        parsed = parse_te_frame(request)
        assert parsed is not None
        payload = parsed.payload
        if payload[0] == TEFileCommand.INIT:
            response_payload = bytes([12, 0, 0, 2, 0])
        elif payload[:2] == bytes([TEFileCommand.GET, TEFileCommand.GET_TYPE_INIT]):
            response_payload = (
                bytes([0, 207, TEFileCommand.FILE_TYPE_FILE])
                + len(PCM_DATA).to_bytes(4, "big")
                + b"207.pcm\x00"
            )
        elif payload[:2] == bytes([TEFileCommand.GET, TEFileCommand.GET_TYPE_DATA]):
            page = int.from_bytes(payload[2:4], "big")
            chunk = PCM_DATA[page * 324 : (page + 1) * 324]
            response_payload = page.to_bytes(2, "big") + chunk
        elif payload[:2] == bytes(
            [TEFileCommand.METADATA, TEFileCommand.METADATA_GET]
        ):
            page = int.from_bytes(payload[4:6], "big")
            body = json.dumps({**METADATA, "crc": 2655139083}).encode("utf-8") + b"\x00"
            response_payload = page.to_bytes(2, "big") + body
        else:
            raise AssertionError(f"unexpected request payload {payload.hex()}")
        response = _response_for(request, response_payload)
        unsolicited = bytes([0xF0, *TE_ID, 0x33, 0x33, 0x01, 0xF7])
        return [unsolicited, response]


def _response_for(request: bytes, payload: bytes, status: int = 0) -> bytes:
    parsed = parse_te_frame(request)
    assert parsed is not None and parsed.request_id is not None
    request_id = parsed.request_id
    flags = BIT_REQUEST_ID_AVAILABLE | ((request_id >> 7) & 0x1F)
    return bytes(
        [
            SYSEX_START,
            *TE_ID,
            parsed.device_id,
            TE_MARKER,
            flags,
            request_id & 0x7F,
            parsed.command,
            status,
            *pack_to_7bit_payload(payload),
            SYSEX_END,
        ]
    )


def test_get_payloads_match_verified_protocol() -> None:
    assert build_file_get_init_payload(207) == bytes([3, 0, 0, 207, 0, 0, 0, 0])
    assert build_file_get_data_payload(12) == bytes([3, 1, 0, 12])


def test_response_matching_rejects_unsolicited_te_sysex() -> None:
    request = build_te_frame(TEFileCommand.COMMAND, bytes([3, 1, 0, 0]), request_id=91)
    matching = _response_for(request, bytes([0, 0, 1, 2, 3]))
    unsolicited = bytes([0xF0, *TE_ID, 0x33, 0x33, 0x01, 0xF7])

    assert sysex_response_matches(request, matching)
    assert not sysex_response_matches(request, unsolicited)


def test_device_file_client_downloads_and_verifies_crc() -> None:
    exchange = FakeDeviceExchange()
    client = DeviceFileClient(
        exchange,
        limits=DeviceDownloadLimits(max_file_bytes=4096),
    )

    download = client.download(207)

    assert download.file_name == "207.pcm"
    assert download.data == PCM_DATA
    assert download.pages == 2
    assert download.metadata["samplerate"] == 46875
    assert download.crc_matches_metadata is True
    assert len(download.sha256) == 64


def test_save_download_creates_content_addressed_pcm_and_wav_bundle(tmp_path) -> None:
    download = DeviceFileClient(FakeDeviceExchange()).download(207)

    artifact = save_device_download(download, tmp_path)
    latest = find_latest_device_artifact(tmp_path, 207)

    assert artifact.raw_path.read_bytes() == PCM_DATA
    assert artifact.wav_path is not None and artifact.wav_path.exists()
    assert latest is not None
    assert latest.bundle_dir == artifact.bundle_dir
    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    assert manifest["crc_matches_metadata"] is True
    assert manifest["sha256"] == download.sha256
    with wave.open(str(artifact.wav_path), "rb") as handle:
        assert handle.getframerate() == 46875
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.readframes(handle.getnframes()) == PCM_DATA


def test_pcm_to_wav_rejects_incomplete_frames() -> None:
    try:
        pcm_to_wav_bytes(b"\x00", METADATA)
    except ValueError as exc:
        assert "frame width" in str(exc)
    else:
        raise AssertionError("incomplete PCM frame should fail")


def test_snapshot_sound_entries_filters_and_sorts(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "node_id": 12,
                        "path": "/sounds/012.pcm",
                        "name": "012.pcm",
                        "kind": "file",
                        "size": 200,
                    },
                    {
                        "node_id": 2,
                        "path": "/sounds/002.pcm",
                        "name": "002.pcm",
                        "kind": "file",
                        "size": 100,
                    },
                    {
                        "node_id": 3000,
                        "path": "/projects/01",
                        "name": "01",
                        "kind": "dir",
                        "size": 0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    entries = load_snapshot_sound_entries(snapshot)

    assert [entry["slot"] for entry in entries] == [2, 12]
    assert [entry["size"] for entry in entries] == [100, 200]


def test_device_download_cli_reports_integrity_paths(tmp_path, monkeypatch, capsys) -> None:
    download = DeviceFileDownload(
        node_id=207,
        file_name="207.pcm",
        flags=TEFileCommand.FILE_TYPE_FILE,
        declared_size=4,
        offset=0,
        chunk_size=512,
        pages=1,
        data=b"\x00\x00\x01\x00",
        metadata=METADATA,
        metadata_text=json.dumps(METADATA),
        sha256="a" * 64,
        crc32=123,
        metadata_crc32=123,
        crc_matches_metadata=True,
    )
    bundle = tmp_path / "bundle"
    artifact = DeviceDownloadArtifact(
        bundle_dir=bundle,
        raw_path=bundle / "207.pcm",
        manifest_path=bundle / "manifest.json",
        metadata_path=bundle / "metadata.json",
        latest_path=tmp_path / "latest.json",
        wav_path=bundle / "207.wav",
    )
    monkeypatch.setattr(
        "ko2_daw.app.download_device_file_live",
        lambda *args, **kwargs: download,
    )
    monkeypatch.setattr(
        "ko2_daw.app.save_device_download",
        lambda *args, **kwargs: artifact,
    )

    result = main(
        [
            "--device-download-node",
            "207",
            "--device-download-dir",
            str(Path(tmp_path) / "library"),
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "device_download_node=207" in output
    assert f"device_download_bundle={bundle}" in output
    assert "device_download_crc_match=True" in output
