"""Tests for read-only EP-133 project archive inspection."""

from __future__ import annotations

import io
import json
import tarfile

import pytest

from ko2_daw.device_transfer import DeviceFileDownload, save_device_download
from ko2_daw.project_archive import compare_project_archives, inspect_project_archive
from ko2_daw.te_sysex import TEFileCommand


def _tar(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


def test_project_archive_decodes_signed_little_endian_pad_assignments() -> None:
    data = _tar(
        {
            "pads/A/p1": b"\x01\xcf\x00rest",
            "pads/D/p12": b"\x01\xff\xff",
            "patterns/1": b"pattern",
        }
    )

    info = inspect_project_archive(data)

    assert [(item.group, item.pad, item.sound_id) for item in info.assignments] == [
        ("A", 1, 207),
        ("D", 12, -1),
    ]
    assert info.other_files == ("patterns/1",)
    assert info.to_dict()["assigned_pad_count"] == 1


def test_project_archive_accepts_live_lowercase_zero_padded_paths() -> None:
    data = _tar(
        {
            "pads/a/p01": b"\x00\x22\x00" + bytes(24),
            "pads/b/p07": b"\x00\x07\x00" + bytes(24),
            "pads/c/p12": bytes(27),
        }
    )

    info = inspect_project_archive(data)

    assert [(item.group, item.pad, item.sound_id, item.assigned) for item in info.assignments] == [
        ("A", 1, 34, True),
        ("B", 7, 7, True),
        ("C", 12, 0, False),
    ]


def test_project_archive_fingerprints_opaque_records_and_patterns() -> None:
    data = _tar(
        {
            "pads/a/p01": b"\x00\x22\x00" + bytes(24),
            "fx_settings": b"\x00\x01\x00\x02",
            "patterns/b07": b"\x01\x02\x03\x04",
            "scenes": b"\x00\x10\x00",
            "settings": b"\x01\x00",
        }
    )

    info = inspect_project_archive(data)
    records = {record.path: record for record in info.binary_records}

    assert info.pattern_count == 1
    assert records["patterns/b07"].kind == "pattern"
    assert records["patterns/b07"].group == "B"
    assert records["patterns/b07"].index == 7
    assert records["fx_settings"].nonzero_byte_count == 2
    assert records["settings"].preview_hex == "0100"
    assert info.to_dict()["schema"] == "ko2-daw.ep133-project-analysis.v2"


def test_project_comparison_reports_pad_and_bounded_binary_changes() -> None:
    before = _tar(
        {
            "pads/a/p01": b"\x00\x22\x00" + bytes(24),
            "patterns/a01": b"\x00\x01\x02\x03\x04\x05",
            "settings": b"\x10\x11",
        }
    )
    after = _tar(
        {
            "pads/a/p01": b"\x00\x23\x00" + bytes(24),
            "patterns/a01": b"\x00\x09\x02\x08\x04\x05",
            "scenes": b"\x20",
        }
    )

    comparison = compare_project_archives(before, after)
    changes = {change.path: change for change in comparison.binary_changes}

    assert comparison.identical is False
    assert comparison.pad_changes[0].before_sound_id == 34
    assert comparison.pad_changes[0].after_sound_id == 35
    assert changes["patterns/a01"].changed_byte_count == 2
    assert [
        (item.start_offset, item.end_offset)
        for item in changes["patterns/a01"].changed_ranges
    ] == [(1, 2), (3, 4)]
    assert changes["scenes"].status == "added"
    assert changes["settings"].status == "removed"


def test_project_archive_rejects_traversal_and_bad_pad_records() -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        inspect_project_archive(_tar({"../escape": b"bad"}))
    with pytest.raises(ValueError, match="shorter"):
        inspect_project_archive(_tar({"pads/A/p1": b"\x00\x01"}))


def test_directory_download_bundle_writes_project_analysis(tmp_path) -> None:
    data = _tar({"pads/B/p4": b"\x00\x7b\x00"})
    download = DeviceFileDownload(
        node_id=3000,
        file_name="01",
        flags=TEFileCommand.FILE_TYPE_DIR,
        declared_size=len(data),
        offset=0,
        chunk_size=512,
        pages=1,
        data=data,
        sha256="1" * 64,
    )

    artifact = save_device_download(download, tmp_path, export_wav=False)

    assert artifact.project_analysis_path is not None
    analysis = json.loads(artifact.project_analysis_path.read_text(encoding="utf-8"))
    assert analysis["assignments"][0]["sound_id"] == 123
    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    assert manifest["project_analysis_file"] == "project_analysis.json"
