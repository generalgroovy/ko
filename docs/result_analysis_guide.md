# Result Analysis Guide

This guide explains how to read the project result artifacts produced by the
KO II companion app and how to turn them into practical decisions without
guessing device semantics.

## Artifact Map

| Artifact | Created by | Purpose | Primary question answered |
| --- | --- | --- | --- |
| `device_snapshot.json` | `--device-snapshot` | Full visible file-tree inventory | Did the visible device inventory change? |
| `project_analysis.json` | project download/save | Per-project TAR summary | Which pads are assigned and which opaque records exist? |
| `project_catalog.json` | `--device-project-catalog` / backup all | Nine-slot project index | Are all local project backups present and verified? |
| `metadata.json` | sound/project download | Device metadata payload | Does metadata agree with the downloaded bytes? |
| `manifest.json` | sound/project download | Immutable bundle index | Which raw, WAV, metadata, and analysis files belong together? |
| `midi_report.json` | `--report-json` | Port and backend discovery | Is EP-133 visible as USB and MIDI? |
| `ko2_device_interaction_capabilities.txt` | `--capability-scan` | Human-readable probe report | Which interactions are confirmed, blocked, or unprobed? |

## Reading `project_analysis.json`

The project analysis is intentionally conservative. It decodes only fields that
have evidence across captured archives and keeps all other data fingerprinted.

Start with these sections:

- `summary.integrity`: use `sha256`, `byte_count`, and `file_count` to confirm
  the raw archive being inspected.
- `summary.pads`: use assignment counts, group coverage, and assigned pad lists
  to understand the playable surface of the archived project.
- `summary.records`: use record counts and byte totals to see whether a project
  has patterns, scenes, settings, and optional `fx_settings`.
- `assignments`: exact pad-to-sound-id rows. Sound id `0` means unassigned.
- `binary_records`: hashes, CRC32 values, byte counts, nonzero byte counts, and
  previews for records that are not semantically decoded.
- `interpretation`: the analysis boundary written into the file so the JSON is
  usable without needing to reread the code.
- `recommended_next_actions`: safe follow-up actions for comparison work.

Do not infer parameter names from `preview_hex` alone. Use controlled
before/after captures and byte-range comparisons before naming any unknown
field.

## Practical Review Flow

1. Confirm the source bundle.
   Check `manifest.json`, then compare its `sha256` and `project_analysis_file`
   with the `project_analysis.json` you are reading.

2. Confirm project shape.
   A normal captured EP-133 project has 48 pad records, `scenes`, and
   `settings`. `fx_settings` can be absent.

3. Review group coverage.
   Use `summary.pads.groups` to see whether a project is sparse, one-group
   focused, or distributed across A-D.

4. Review sound references.
   Pad `sound_id` values refer to `/sounds/<id>.pcm`. A pad assignment confirms
   a reference, not that the sound content was separately backed up.

5. Review opaque records.
   Use `binary_records` to identify patterns and structural records. Hashes are
   useful for exact comparisons even when the internal fields are unknown.

6. Compare before/after archives.
   Use project comparison output for pad changes and half-open changed byte
   ranges. Treat a changed range as evidence to investigate, not a decoded field.

## Decision Table

| Finding | Meaning | Recommended action |
| --- | --- | --- |
| `assigned_pad_count` increased | More pads reference sounds | Compare assignments and verify related sound backups exist. |
| `pattern_count` changed | Pattern files were added or removed | Compare binary records and preserve both raw archives. |
| `scenes` hash changed | Scene data changed, semantics still opaque | Use controlled edit captures to isolate which action changed bytes. |
| `settings` hash changed | Project settings changed, semantics still opaque | Compare byte ranges and document the exact front-panel action. |
| Missing `scenes` or `settings` | Archive is structurally incomplete for observed EP-133 captures | Keep the raw file but do not use it as a normal project baseline. |
| Metadata CRC mismatch | Device metadata does not match downloaded raw bytes | Re-download before trusting derived WAV or analysis output. |
| Inventory SHA changed | Visible device tree changed | Compare snapshots and confirm whether the change was intentional. |

## Usability Rules

- Keep raw downloaded bundles immutable. Re-run analysis instead of editing
  generated JSON by hand.
- Store experiments by scenario and date under `daw_projects/` or
  `slurm/results/`, not in the repository root.
- Put failure logs in `slurm/errors/` when running on a cluster.
- Promote a field from opaque to decoded only after at least two controlled
  captures isolate the same byte behavior.
- Prefer comparison reports for reverse engineering. Single snapshots describe
  state; comparisons provide evidence of cause.
