"""Read-only inspection and comparison of EP-133 project TAR archives."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import io
import re
import tarfile
import zlib


PAD_PATH = re.compile(r"^pads/([A-Da-d])/p(\d{1,2})$")
PATTERN_PATH = re.compile(r"^patterns/([A-Da-d])(\d{2})$")


@dataclass(frozen=True)
class ProjectPadAssignment:
    """One project pad file decoded without modifying the archive."""

    group: str
    pad: int
    sound_id: int
    path: str
    byte_count: int

    @property
    def assigned(self) -> bool:
        return self.sound_id > 0


@dataclass(frozen=True)
class ProjectBinaryRecord:
    """Opaque project member fingerprinted without assigning field semantics."""

    path: str
    kind: str
    byte_count: int
    sha256: str
    crc32: int
    nonzero_byte_count: int
    preview_hex: str
    group: str = ""
    index: int | None = None


@dataclass(frozen=True)
class ProjectArchiveInfo:
    """Safe summary of an EP-133 project archive."""

    sha256: str
    byte_count: int
    file_count: int
    directory_count: int
    assignments: tuple[ProjectPadAssignment, ...]
    other_files: tuple[str, ...]
    binary_records: tuple[ProjectBinaryRecord, ...] = ()

    @property
    def assigned_pad_count(self) -> int:
        return sum(item.assigned for item in self.assignments)

    @property
    def pattern_count(self) -> int:
        return sum(item.kind == "pattern" for item in self.binary_records)

    def to_dict(self) -> dict[str, object]:
        assignments = [
            asdict(item) | {"assigned": item.assigned} for item in self.assignments
        ]
        binary_records = [asdict(item) for item in self.binary_records]
        groups = ("A", "B", "C", "D")
        group_summary = {}
        for group in groups:
            group_assignments = [
                item for item in self.assignments if item.group == group
            ]
            assigned = [item for item in group_assignments if item.assigned]
            group_summary[group] = {
                "assigned_pad_count": len(assigned),
                "unassigned_pad_count": len(group_assignments) - len(assigned),
                "distinct_sound_count": len({item.sound_id for item in assigned}),
                "assigned_pads": [
                    {"pad": item.pad, "sound_id": item.sound_id} for item in assigned
                ],
            }
        record_count_by_kind: dict[str, int] = {}
        bytes_by_kind: dict[str, int] = {}
        for item in self.binary_records:
            record_count_by_kind[item.kind] = (
                record_count_by_kind.get(item.kind, 0) + 1
            )
            bytes_by_kind[item.kind] = bytes_by_kind.get(item.kind, 0) + item.byte_count
        required_records = {"scenes", "settings"}
        present_paths = {item.path for item in self.binary_records}
        coverage = (
            self.assigned_pad_count / len(self.assignments)
            if self.assignments
            else 0.0
        )
        return {
            "schema": "ko2-daw.ep133-project-analysis.v2",
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "file_count": self.file_count,
            "directory_count": self.directory_count,
            "assigned_pad_count": self.assigned_pad_count,
            "pattern_count": self.pattern_count,
            "summary": {
                "integrity": {
                    "sha256": self.sha256,
                    "byte_count": self.byte_count,
                    "file_count": self.file_count,
                    "directory_count": self.directory_count,
                },
                "pads": {
                    "total_pad_records": len(self.assignments),
                    "assigned_pad_count": self.assigned_pad_count,
                    "unassigned_pad_count": (
                        len(self.assignments) - self.assigned_pad_count
                    ),
                    "assignment_coverage_percent": round(coverage * 100.0, 2),
                    "groups": group_summary,
                },
                "records": {
                    "binary_record_count": len(self.binary_records),
                    "pattern_count": self.pattern_count,
                    "record_count_by_kind": dict(sorted(record_count_by_kind.items())),
                    "bytes_by_kind": dict(sorted(bytes_by_kind.items())),
                    "required_records_present": sorted(required_records & present_paths),
                    "required_records_missing": sorted(required_records - present_paths),
                    "opaque_record_count": sum(
                        item.kind
                        in {"unknown", "pattern", "scenes", "settings", "fx_settings"}
                        for item in self.binary_records
                    ),
                },
            },
            "interpretation": [
                "Pad assignments decode only the verified signed little-endian sound id at bytes 1-2.",
                "Sound id 0 means the pad is unassigned; positive values reference /sounds/<id>.pcm.",
                "Pattern, scenes, settings, fx_settings, and unknown files are fingerprinted but not semantically decoded.",
                "Use sha256, crc32, byte_count, and changed byte ranges for exact comparisons before assigning field meanings.",
            ],
            "recommended_next_actions": [
                "Compare this analysis with another project archive before and after one controlled device edit.",
                "Treat changed opaque byte ranges as evidence for future reverse engineering, not as decoded parameters.",
                "Keep the raw TAR bundle as the source of truth; this JSON is an index for inspection and comparison.",
            ],
            "assignments": assignments,
            "binary_records": binary_records,
            "other_files": list(self.other_files),
        }


@dataclass(frozen=True)
class ProjectPadChange:
    group: str
    pad: int
    before_sound_id: int | None
    after_sound_id: int | None


@dataclass(frozen=True)
class ProjectByteRange:
    """Half-open changed byte range [start_offset, end_offset)."""

    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class ProjectBinaryChange:
    path: str
    status: str
    before_byte_count: int
    after_byte_count: int
    before_sha256: str
    after_sha256: str
    changed_byte_count: int
    changed_ranges: tuple[ProjectByteRange, ...]
    ranges_truncated: bool = False


@dataclass(frozen=True)
class ProjectArchiveComparison:
    before_sha256: str
    after_sha256: str
    pad_changes: tuple[ProjectPadChange, ...]
    binary_changes: tuple[ProjectBinaryChange, ...]

    @property
    def identical(self) -> bool:
        return (
            self.before_sha256 == self.after_sha256
            and not self.pad_changes
            and not self.binary_changes
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "ko2-daw.ep133-project-comparison.v1",
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "identical": self.identical,
            "pad_changes": [asdict(item) for item in self.pad_changes],
            "binary_changes": [
                {
                    **asdict(item),
                    "changed_ranges": [
                        asdict(byte_range) for byte_range in item.changed_ranges
                    ],
                }
                for item in self.binary_changes
            ],
        }


def inspect_project_archive(
    data: bytes,
    *,
    max_members: int = 4096,
    max_member_bytes: int = 8 * 1024 * 1024,
    max_total_bytes: int = 64 * 1024 * 1024,
) -> ProjectArchiveInfo:
    """Inspect a TAR in memory and decode only independently verified fields.

    No member is extracted to disk. Link entries, absolute paths, traversal
    paths, duplicate paths, oversized members, and malformed pad records are
    rejected. Unknown records remain opaque and receive integrity fingerprints.
    """

    members, directory_count = _read_project_archive(
        data,
        max_members=max_members,
        max_member_bytes=max_member_bytes,
        max_total_bytes=max_total_bytes,
    )
    return _build_archive_info(data, members, directory_count)


def compare_project_archives(
    before: bytes,
    after: bytes,
    *,
    max_changed_ranges: int = 128,
    max_members: int = 4096,
    max_member_bytes: int = 8 * 1024 * 1024,
    max_total_bytes: int = 64 * 1024 * 1024,
) -> ProjectArchiveComparison:
    """Compare two safe project archives without assigning unknown semantics."""

    if max_changed_ranges < 1:
        raise ValueError("max_changed_ranges must be positive.")
    before_members, before_dirs = _read_project_archive(
        before,
        max_members=max_members,
        max_member_bytes=max_member_bytes,
        max_total_bytes=max_total_bytes,
    )
    after_members, after_dirs = _read_project_archive(
        after,
        max_members=max_members,
        max_member_bytes=max_member_bytes,
        max_total_bytes=max_total_bytes,
    )
    before_info = _build_archive_info(before, before_members, before_dirs)
    after_info = _build_archive_info(after, after_members, after_dirs)

    before_pads = {
        (item.group, item.pad): item.sound_id for item in before_info.assignments
    }
    after_pads = {
        (item.group, item.pad): item.sound_id for item in after_info.assignments
    }
    pad_changes = tuple(
        ProjectPadChange(
            group=group,
            pad=pad,
            before_sound_id=before_pads.get((group, pad)),
            after_sound_id=after_pads.get((group, pad)),
        )
        for group, pad in sorted(before_pads.keys() | after_pads.keys())
        if before_pads.get((group, pad)) != after_pads.get((group, pad))
    )

    before_binary = {
        path: payload
        for path, payload in before_members.items()
        if PAD_PATH.fullmatch(path) is None
    }
    after_binary = {
        path: payload
        for path, payload in after_members.items()
        if PAD_PATH.fullmatch(path) is None
    }
    binary_changes: list[ProjectBinaryChange] = []
    for path in sorted(before_binary.keys() | after_binary.keys()):
        before_payload = before_binary.get(path)
        after_payload = after_binary.get(path)
        if before_payload == after_payload:
            continue
        ranges, changed_count, truncated = _changed_byte_ranges(
            before_payload or b"",
            after_payload or b"",
            max_ranges=max_changed_ranges,
        )
        binary_changes.append(
            ProjectBinaryChange(
                path=path,
                status=(
                    "added"
                    if before_payload is None
                    else "removed"
                    if after_payload is None
                    else "changed"
                ),
                before_byte_count=len(before_payload or b""),
                after_byte_count=len(after_payload or b""),
                before_sha256=(
                    hashlib.sha256(before_payload).hexdigest()
                    if before_payload is not None
                    else ""
                ),
                after_sha256=(
                    hashlib.sha256(after_payload).hexdigest()
                    if after_payload is not None
                    else ""
                ),
                changed_byte_count=changed_count,
                changed_ranges=ranges,
                ranges_truncated=truncated,
            )
        )

    return ProjectArchiveComparison(
        before_sha256=before_info.sha256,
        after_sha256=after_info.sha256,
        pad_changes=pad_changes,
        binary_changes=tuple(binary_changes),
    )


def validate_ep133_project_structure(info: ProjectArchiveInfo) -> None:
    """Require the structural records shared by every captured EP-133 project."""

    expected_pads = {
        (group, pad)
        for group in ("A", "B", "C", "D")
        for pad in range(1, 13)
    }
    actual_pads = {(item.group, item.pad) for item in info.assignments}
    if actual_pads != expected_pads:
        missing = sorted(expected_pads - actual_pads)
        extra = sorted(actual_pads - expected_pads)
        raise ValueError(
            "EP-133 project archive must contain exactly 48 pads; "
            f"missing={missing}, extra={extra}."
        )
    binary_paths = {item.path for item in info.binary_records}
    missing_records = sorted({"scenes", "settings"} - binary_paths)
    if missing_records:
        raise ValueError(
            "EP-133 project archive is missing required records: "
            + ", ".join(missing_records)
        )


def _read_project_archive(
    data: bytes,
    *,
    max_members: int,
    max_member_bytes: int,
    max_total_bytes: int,
) -> tuple[dict[str, bytes], int]:
    if len(data) < 512:
        raise ValueError("EP-133 project archive is too small to be a TAR file.")
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except (tarfile.TarError, OSError) as exc:
        raise ValueError(f"Invalid EP-133 project TAR: {exc}") from exc

    files: dict[str, bytes] = {}
    directory_count = 0
    total_bytes = 0
    with archive:
        members = archive.getmembers()
        if len(members) > max_members:
            raise ValueError(
                f"Project archive has {len(members)} members; limit is {max_members}."
            )
        seen: set[str] = set()
        for member in members:
            path = _safe_member_path(member.name)
            if path in seen:
                raise ValueError(f"Project archive contains duplicate path: {path}")
            seen.add(path)
            if member.issym() or member.islnk():
                raise ValueError(f"Project archive contains unsupported link: {path}")
            if member.isdir():
                directory_count += 1
                continue
            if not member.isfile():
                raise ValueError(
                    f"Project archive contains unsupported member type: {path}"
                )
            if member.size < 0 or member.size > max_member_bytes:
                raise ValueError(
                    f"Project archive member {path!r} is {member.size} bytes; "
                    f"limit is {max_member_bytes}."
                )
            total_bytes += member.size
            if total_bytes > max_total_bytes:
                raise ValueError(
                    f"Project archive file payload exceeds {max_total_bytes} bytes."
                )
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"Could not read project archive member: {path}")
            payload = handle.read(max_member_bytes + 1)
            if len(payload) != member.size:
                raise ValueError(f"Project archive member was truncated: {path}")
            files[path] = payload
    return files, directory_count


def _build_archive_info(
    data: bytes,
    members: dict[str, bytes],
    directory_count: int,
) -> ProjectArchiveInfo:
    assignments: list[ProjectPadAssignment] = []
    binary_records: list[ProjectBinaryRecord] = []
    other_files: list[str] = []

    for path, payload in members.items():
        pad_match = PAD_PATH.fullmatch(path)
        if pad_match is not None:
            pad = int(pad_match.group(2))
            if not 1 <= pad <= 12:
                raise ValueError(
                    f"Project archive pad number is outside 1-12: {path}"
                )
            if len(payload) < 3:
                raise ValueError(
                    f"Project pad member is shorter than 3 bytes: {path}"
                )
            assignments.append(
                ProjectPadAssignment(
                    group=pad_match.group(1).upper(),
                    pad=pad,
                    sound_id=int.from_bytes(
                        payload[1:3],
                        "little",
                        signed=True,
                    ),
                    path=path,
                    byte_count=len(payload),
                )
            )
            continue

        kind = "unknown"
        group = ""
        index: int | None = None
        pattern_match = PATTERN_PATH.fullmatch(path)
        if pattern_match is not None:
            kind = "pattern"
            group = pattern_match.group(1).upper()
            index = int(pattern_match.group(2))
        elif path in {"fx_settings", "scenes", "settings"}:
            kind = path
        other_files.append(path)
        binary_records.append(
            ProjectBinaryRecord(
                path=path,
                kind=kind,
                byte_count=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                crc32=zlib.crc32(payload) & 0xFFFFFFFF,
                nonzero_byte_count=sum(value != 0 for value in payload),
                preview_hex=payload[:32].hex(),
                group=group,
                index=index,
            )
        )

    assignments.sort(key=lambda item: (item.group, item.pad))
    binary_records.sort(key=lambda item: item.path)
    other_files.sort()
    return ProjectArchiveInfo(
        sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
        file_count=len(members),
        directory_count=directory_count,
        assignments=tuple(assignments),
        other_files=tuple(other_files),
        binary_records=tuple(binary_records),
    )


def _changed_byte_ranges(
    before: bytes,
    after: bytes,
    *,
    max_ranges: int,
) -> tuple[tuple[ProjectByteRange, ...], int, bool]:
    length = max(len(before), len(after))
    ranges: list[ProjectByteRange] = []
    changed_count = 0
    range_start: int | None = None
    truncated = False

    for offset in range(length):
        changed = (
            offset >= len(before)
            or offset >= len(after)
            or before[offset] != after[offset]
        )
        if changed:
            changed_count += 1
            if range_start is None:
                range_start = offset
        elif range_start is not None:
            if len(ranges) < max_ranges:
                ranges.append(ProjectByteRange(range_start, offset))
            else:
                truncated = True
            range_start = None
    if range_start is not None:
        if len(ranges) < max_ranges:
            ranges.append(ProjectByteRange(range_start, length))
        else:
            truncated = True
    return tuple(ranges), changed_count, truncated


def _safe_member_path(value: str) -> str:
    path = str(value).replace("\\", "/").strip("/")
    pieces = path.split("/")
    if (
        not path
        or value.startswith(("/", "\\"))
        or any(piece in {"", ".", ".."} for piece in pieces)
    ):
        raise ValueError(f"Unsafe project archive path: {value!r}")
    if ":" in pieces[0]:
        raise ValueError(f"Unsafe project archive path: {value!r}")
    return path
