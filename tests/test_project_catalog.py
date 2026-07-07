"""Tests for integrity-checked EP-133 project catalog and backup."""

from __future__ import annotations

import hashlib
import io
import tarfile

from ko2_daw.app import main
from ko2_daw.device_transfer import DeviceFileDownload, save_device_download
from ko2_daw.project_catalog import (
    backup_project_archives,
    build_project_catalog,
    save_project_catalog,
)
from ko2_daw.te_sysex import TEFileCommand


def _tar(sound_id: int, pattern: bytes = b"\x00\x01") -> bytes:
    output = io.BytesIO()
    entries = {
        "fx_settings": bytes(160),
        "patterns/a01": pattern,
        "scenes": bytes(712),
        "settings": bytes(222),
    }
    for group in "abcd":
        for pad in range(1, 13):
            assigned = sound_id if (group, pad) == ("a", 1) else 0
            entries[f"pads/{group}/p{pad:02d}"] = (
                b"\x00"
                + int(assigned).to_bytes(2, "little", signed=True)
                + bytes(24)
            )
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


def _download(node_id: int, name: str, data: bytes) -> DeviceFileDownload:
    return DeviceFileDownload(
        node_id=node_id,
        file_name=name,
        flags=TEFileCommand.FILE_TYPE_DIR,
        declared_size=len(data),
        offset=0,
        chunk_size=512,
        pages=4,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )


class FakeClient:
    def __init__(self, downloads: dict[int, DeviceFileDownload]):
        self.downloads = downloads
        self.requested: list[int] = []

    def download(self, node_id, *, include_metadata, progress):
        assert include_metadata is False
        self.requested.append(node_id)
        result = self.downloads[node_id]
        progress(len(result.data), len(result.data), "data")
        return result


def test_project_catalog_verifies_archives_and_writes_v2_analysis(tmp_path) -> None:
    data = _tar(34)
    save_device_download(_download(3000, "01", data), tmp_path, export_wav=False)

    catalog = build_project_catalog(tmp_path, projects=((1, 3000), (2, 4000)))
    path = save_project_catalog(catalog)

    assert catalog.verified_count == 1
    assert catalog.missing_nodes == (4000,)
    assert catalog.entries[0].assigned_pad_count == 1
    assert catalog.entries[0].pattern_count == 1
    assert catalog.entries[0].scenes_bytes == 712
    assert path.exists()
    analysis = (
        next(tmp_path.glob("03000_*/latest.json")).parent
        / catalog.entries[0].sha256
        / "project_analysis.json"
    ).read_text(encoding="utf-8")
    assert "ko2-daw.ep133-project-analysis.v2" in analysis


def test_project_catalog_marks_tampered_raw_bundle_invalid(tmp_path) -> None:
    data = _tar(34)
    artifact = save_device_download(
        _download(3000, "01", data),
        tmp_path,
        export_wav=False,
    )
    artifact.raw_path.write_bytes(data + b"tampered")

    catalog = build_project_catalog(tmp_path, projects=((1, 3000),))

    assert catalog.entries[0].status == "invalid"
    assert "does not match manifest" in catalog.entries[0].error


def test_project_backup_skips_verified_and_downloads_missing(tmp_path) -> None:
    first = _tar(34)
    second = _tar(35, b"\x02\x03")
    save_device_download(_download(3000, "01", first), tmp_path, export_wav=False)
    client = FakeClient({4000: _download(4000, "02", second)})
    events = []

    result = backup_project_archives(
        client,
        tmp_path,
        projects=((1, 3000), (2, 4000)),
        progress=events.append,
    )

    assert client.requested == [4000]
    assert result.skipped_nodes == (3000,)
    assert result.downloaded_nodes == (4000,)
    assert result.catalog.verified_count == 2
    assert result.catalog_path.exists()
    assert any(event.stage == "skipped-verified" for event in events)
    assert any(event.stage == "saved" for event in events)


def test_project_catalog_cli_reports_local_integrity(tmp_path, capsys) -> None:
    data = _tar(34)
    save_device_download(_download(3000, "01", data), tmp_path, export_wav=False)

    result = main(
        [
            "--device-project-catalog",
            "--device-download-dir",
            str(tmp_path),
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "project_catalog_verified=1" in output
    assert "project_catalog_missing=4000,5000,6000,7000,8000,9000,10000,11000" in output
