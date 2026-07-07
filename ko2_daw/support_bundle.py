"""Support bundle export for debugging connected KO II sessions."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import platform
import zipfile

from ko2_daw.config import load_app_settings
from ko2_daw.diagnostics import readiness_report
from ko2_daw.midi import midi_capability_report
from ko2_daw.routing import resolve_ko2_route


def create_support_bundle(
    output_dir: str | Path = "daw_projects",
    *,
    settings_path: str | Path = "daw_projects/app_settings.json",
    project_root: str | Path = "daw_projects",
) -> Path:
    """Create a timestamped ZIP with non-destructive diagnostics and local state."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_path = out_dir / f"support_bundle_{timestamp}.zip"

    report = midi_capability_report()
    settings = load_app_settings(settings_path)
    try:
        preferred = settings.preferred_route if settings.preferred_route != "manual" else "auto"
        route = resolve_ko2_route(report, preferred)
        route_payload = route.__dict__
    except Exception as exc:  # defensive: support bundle should not fail on route errors
        route_payload = {"error": str(exc)}

    payloads: dict[str, object] = {
        "manifest.json": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "app": "ko2-daw",
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "midi_report.json": report,
        "readiness_report.json": readiness_report(report),
        "route.json": route_payload,
        "settings.json": settings.to_dict(),
    }

    project_path = Path(project_root)
    optional_files = [
        project_path / "hardware_file_cache.json",
        project_path / "ep133_device_snapshot.json",
        project_path / "device_library" / "project_catalog.json",
        project_path / "ko2_state.json",
        project_path / "companion_session.json",
        project_path / "hardware_performance_smoke.json",
        project_path / "hardware_performance_smoke.mid",
        Path("docs") / "ko2_device_interaction_capabilities.txt",
        Path("docs") / "ep133_file_protocol.md",
    ]
    device_library_metadata = [
        *sorted((project_path / "device_library").glob("*/latest.json")),
        *sorted((project_path / "device_library").glob("*/*/manifest.json")),
        *sorted((project_path / "device_library").glob("*/*/metadata.json")),
        *sorted((project_path / "device_library").glob("*/*/project_analysis.json")),
    ]
    editable_project_files = [
        *sorted((project_path / "audio_projects").glob("*.json")),
        *sorted(project_path.glob("*arrang*.json")),
        *sorted(project_path.glob("*performance*.json")),
    ]

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        written_paths: set[str] = set()

        def add_file(path: Path) -> None:
            archive_name = f"files/{path.as_posix()}"
            if path.is_file() and archive_name not in written_paths:
                archive.write(path, archive_name)
                written_paths.add(archive_name)

        for name, payload in payloads.items():
            archive.writestr(name, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        for path in optional_files:
            if path.exists():
                add_file(path)
        for path in device_library_metadata[:5000]:
            add_file(path)
        for path in editable_project_files[:500]:
            add_file(path)

    return bundle_path.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a KO II DAW support bundle.")
    parser.add_argument("--output-dir", default="daw_projects")
    parser.add_argument("--settings", default="daw_projects/app_settings.json")
    parser.add_argument("--project-root", default="daw_projects")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = create_support_bundle(
        args.output_dir,
        settings_path=args.settings,
        project_root=args.project_root,
    )
    print(f"support_bundle={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
