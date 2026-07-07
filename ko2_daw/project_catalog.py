"""Integrity-checked local catalog and resumable backup for EP-133 projects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from ko2_daw.device_snapshot import ReadOnlySysexSession
from ko2_daw.device_transfer import (
    DeviceDownloadArtifact,
    DeviceDownloadLimits,
    DeviceFileClient,
    find_latest_device_artifact,
    save_device_download,
)
from ko2_daw.io_utils import atomic_write_text
from ko2_daw.midi import midi_capability_report
from ko2_daw.project_archive import (
    ProjectArchiveInfo,
    inspect_project_archive,
    validate_ep133_project_structure,
)
from ko2_daw.routing import KO2Route, resolve_ko2_route


PROJECT_SLOTS: tuple[tuple[int, int], ...] = tuple(
    (slot, 2000 + slot * 1000) for slot in range(1, 10)
)
PROJECT_NODES: tuple[int, ...] = tuple(node for _slot, node in PROJECT_SLOTS)


@dataclass(frozen=True)
class ProjectCatalogEntry:
    slot: int
    node_id: int
    status: str
    name: str = ""
    byte_count: int = 0
    pages: int = 0
    sha256: str = ""
    captured_at: str = ""
    bundle_dir: str = ""
    raw_path: str = ""
    file_count: int = 0
    directory_count: int = 0
    assigned_pad_count: int = 0
    pattern_count: int = 0
    fx_settings_bytes: int = 0
    scenes_bytes: int = 0
    settings_bytes: int = 0
    error: str = ""

    @property
    def verified(self) -> bool:
        return self.status == "verified"


@dataclass(frozen=True)
class ProjectCatalog:
    generated_at: str
    library_root: str
    entries: tuple[ProjectCatalogEntry, ...]
    integrity_sha256: str

    @property
    def verified_count(self) -> int:
        return sum(entry.verified for entry in self.entries)

    @property
    def missing_nodes(self) -> tuple[int, ...]:
        return tuple(entry.node_id for entry in self.entries if not entry.verified)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "ko2-daw.ep133-project-catalog.v1",
            "generated_at": self.generated_at,
            "library_root": self.library_root,
            "summary": {
                "expected_projects": len(self.entries),
                "verified_projects": self.verified_count,
                "missing_or_invalid_projects": len(self.missing_nodes),
                "integrity_sha256": self.integrity_sha256,
            },
            "entries": [asdict(entry) for entry in self.entries],
        }


@dataclass(frozen=True)
class ProjectBackupEvent:
    node_id: int
    slot: int
    project_index: int
    project_total: int
    stage: str
    bytes_done: int = 0
    bytes_total: int = 0


@dataclass(frozen=True)
class ProjectBackupResult:
    catalog: ProjectCatalog
    catalog_path: Path
    downloaded_nodes: tuple[int, ...]
    skipped_nodes: tuple[int, ...]
    artifacts: tuple[DeviceDownloadArtifact, ...]


ProjectBackupProgress = Callable[[ProjectBackupEvent], None]


def build_project_catalog(
    root: str | Path,
    *,
    projects: Iterable[tuple[int, int]] = PROJECT_SLOTS,
    refresh_analysis: bool = True,
) -> ProjectCatalog:
    """Verify latest project bundles and build a deterministic local index."""

    library_root = Path(root).resolve()
    entries = tuple(
        _catalog_entry(
            library_root,
            slot=int(slot),
            node_id=int(node_id),
            refresh_analysis=refresh_analysis,
        )
        for slot, node_id in projects
    )
    canonical_entries = [
        {
            "slot": entry.slot,
            "node_id": entry.node_id,
            "status": entry.status,
            "sha256": entry.sha256,
            "byte_count": entry.byte_count,
            "file_count": entry.file_count,
            "directory_count": entry.directory_count,
            "assigned_pad_count": entry.assigned_pad_count,
            "pattern_count": entry.pattern_count,
            "fx_settings_bytes": entry.fx_settings_bytes,
            "scenes_bytes": entry.scenes_bytes,
            "settings_bytes": entry.settings_bytes,
        }
        for entry in entries
    ]
    canonical = json.dumps(
        canonical_entries,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ProjectCatalog(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        library_root=str(library_root),
        entries=entries,
        integrity_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def save_project_catalog(
    catalog: ProjectCatalog,
    path: str | Path | None = None,
) -> Path:
    target = (
        Path(path)
        if path is not None
        else Path(catalog.library_root) / "project_catalog.json"
    )
    return atomic_write_text(
        target,
        json.dumps(catalog.to_dict(), indent=2, sort_keys=True) + "\n",
    )


def backup_project_archives(
    client: DeviceFileClient,
    root: str | Path,
    *,
    projects: Iterable[tuple[int, int]] = PROJECT_SLOTS,
    force: bool = False,
    progress: ProjectBackupProgress | None = None,
) -> ProjectBackupResult:
    """Download missing projects sequentially, never interrupting an active GET."""

    library_root = Path(root).resolve()
    project_list = tuple((int(slot), int(node)) for slot, node in projects)
    initial = build_project_catalog(
        library_root,
        projects=project_list,
        refresh_analysis=True,
    )
    verified = {entry.node_id for entry in initial.entries if entry.verified}
    downloaded: list[int] = []
    skipped: list[int] = []
    artifacts: list[DeviceDownloadArtifact] = []

    for index, (slot, node_id) in enumerate(project_list, start=1):
        if not force and node_id in verified:
            skipped.append(node_id)
            _notify(
                progress,
                ProjectBackupEvent(
                    node_id=node_id,
                    slot=slot,
                    project_index=index,
                    project_total=len(project_list),
                    stage="skipped-verified",
                ),
            )
            continue

        _notify(
            progress,
            ProjectBackupEvent(
                node_id=node_id,
                slot=slot,
                project_index=index,
                project_total=len(project_list),
                stage="starting",
            ),
        )

        def file_progress(done: int, total: int, stage: str) -> None:
            _notify(
                progress,
                ProjectBackupEvent(
                    node_id=node_id,
                    slot=slot,
                    project_index=index,
                    project_total=len(project_list),
                    stage=stage,
                    bytes_done=done,
                    bytes_total=total,
                ),
            )

        download = client.download(
            node_id,
            include_metadata=False,
            progress=file_progress,
        )
        # Reject malformed or unrelated directory payloads before updating latest.json.
        if not download.is_directory_archive:
            raise ValueError(
                f"Device node {node_id} did not return a directory archive."
            )
        project_info = inspect_project_archive(download.data)
        validate_ep133_project_structure(project_info)
        artifact = save_device_download(
            download,
            library_root,
            export_wav=False,
        )
        downloaded.append(node_id)
        artifacts.append(artifact)
        _notify(
            progress,
            ProjectBackupEvent(
                node_id=node_id,
                slot=slot,
                project_index=index,
                project_total=len(project_list),
                stage="saved",
                bytes_done=download.downloaded_size,
                bytes_total=download.downloaded_size,
            ),
        )

    catalog = build_project_catalog(
        library_root,
        projects=project_list,
        refresh_analysis=True,
    )
    catalog_path = save_project_catalog(catalog)
    return ProjectBackupResult(
        catalog=catalog,
        catalog_path=catalog_path,
        downloaded_nodes=tuple(downloaded),
        skipped_nodes=tuple(skipped),
        artifacts=tuple(artifacts),
    )


def backup_project_archives_live(
    root: str | Path,
    *,
    projects: Iterable[tuple[int, int]] = PROJECT_SLOTS,
    force: bool = False,
    limits: DeviceDownloadLimits | None = None,
    midi_report: dict[str, object] | None = None,
    route: KO2Route | None = None,
    progress: ProjectBackupProgress | None = None,
) -> ProjectBackupResult:
    report = midi_report or midi_capability_report()
    resolved_route = route or resolve_ko2_route(report, "usb-midi")
    if not resolved_route.input_port or not resolved_route.output_port:
        raise RuntimeError(
            "A visible EP-133 MIDI input and output are required for project backup."
        )
    with ReadOnlySysexSession(
        resolved_route.input_port,
        resolved_route.output_port,
    ) as session:
        client = DeviceFileClient(session.send_raw, limits=limits)
        return backup_project_archives(
            client,
            root,
            projects=projects,
            force=force,
            progress=progress,
        )


def _catalog_entry(
    library_root: Path,
    *,
    slot: int,
    node_id: int,
    refresh_analysis: bool,
) -> ProjectCatalogEntry:
    try:
        artifact = find_latest_device_artifact(library_root, node_id)
        if artifact is None:
            return ProjectCatalogEntry(
                slot=slot,
                node_id=node_id,
                status="missing",
            )
        manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("node_id", -1)) != node_id:
            raise ValueError(
                f"Manifest node {manifest.get('node_id')} does not match {node_id}."
            )
        raw = artifact.raw_path.read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        expected_sha = str(manifest.get("sha256") or "")
        if actual_sha != expected_sha:
            raise ValueError(
                f"Raw SHA-256 {actual_sha} does not match manifest {expected_sha}."
            )
        if artifact.bundle_dir.name != expected_sha:
            raise ValueError("Bundle directory does not match its content hash.")
        info = inspect_project_archive(raw)
        validate_ep133_project_structure(info)
        if info.sha256 != expected_sha:
            raise ValueError("Project parser hash does not match the manifest.")
        if refresh_analysis and artifact.project_analysis_path is not None:
            atomic_write_text(
                artifact.project_analysis_path,
                json.dumps(info.to_dict(), indent=2, sort_keys=True) + "\n",
            )
        records = {record.path: record for record in info.binary_records}
        return ProjectCatalogEntry(
            slot=slot,
            node_id=node_id,
            status="verified",
            name=str(manifest.get("file_name") or f"{slot:02d}"),
            byte_count=len(raw),
            pages=int(manifest.get("pages") or 0),
            sha256=expected_sha,
            captured_at=str(manifest.get("captured_at") or ""),
            bundle_dir=str(artifact.bundle_dir),
            raw_path=str(artifact.raw_path),
            file_count=info.file_count,
            directory_count=info.directory_count,
            assigned_pad_count=info.assigned_pad_count,
            pattern_count=info.pattern_count,
            fx_settings_bytes=_record_size(records, "fx_settings"),
            scenes_bytes=_record_size(records, "scenes"),
            settings_bytes=_record_size(records, "settings"),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return ProjectCatalogEntry(
            slot=slot,
            node_id=node_id,
            status="invalid",
            error=str(exc),
        )


def _record_size(
    records: dict[str, object],
    path: str,
) -> int:
    record = records.get(path)
    return int(getattr(record, "byte_count", 0))


def _notify(
    callback: ProjectBackupProgress | None,
    event: ProjectBackupEvent,
) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        # UI/reporting failures must not abandon an active device GET transaction.
        return
