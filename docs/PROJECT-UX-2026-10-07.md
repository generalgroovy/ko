# KO II: a clearer local workspace

Base: `2df8c2609f605699ef72b618cd8be0db94fcd602` (`origin/main`). Candidate branch: `codex/ux-clarity-2026-10-07`. All ten pre-existing untracked pytest directories are preserved. Main and deployment remain owned by the lead.

## Changes

The former prominent Library card opened the connected-device library, while the local Samples workflow had no home action. Home now groups Samples, Compose, Audio and Perform separately from Device Files, Device Library, Projects and Settings. Cards are native buttons with visible keyboard focus, Space and Enter activation. Samples returns directly to the local table and focuses it. Less frequent MIDI detection, protocol inspection and communication controls remain in Tools.

Samples starts with a concrete import instruction and changes to the selected file's name. Trim/slice follows import in the action order. Open Library and Save Library describe their purpose in ordinary language, with adjacent copy explaining that JSON keeps file references, not audio. Format details reveals the secondary technical columns; both scrollbars preserve access to long lists and paths. MIDI triggering remains distinct from local playback and retains the existing routing gate.

The editor keeps exact numeric precision and keyboard frame adjustment. Reading or saving disables the range inputs; cancellation recovers them after the worker finishes. Select all names the full-range reset. A failed or cancelled initial read offers Retry read. The idle Cancel button becomes Close. Completed exports show a selectable full output-folder path, separate from the brief completion status. PCM writing, frame partitioning, original-file preservation and atomic library insertion are unchanged.

## Validation

- Local Windows/Python 3.14: `python -m pytest -q -rs --basetemp=C:/Users/sende/AppData/Local/Temp/ko-ux-20261007-tests` — **215 passed, 1 skipped**. Existing symlink test needs platform permission.
- Ruff, Black check, compilation and diff whitespace passed.
- `tools/check_sample_editor_ui.py` extends the real Tk checks with locked ranges, cancellation recovery, output location, retry after fixing a malformed source and idle Close. Existing exact PCM, keyboard and 680/460-pixel checks remain.
- `tools/check_workspace_ui.py` constructs the complete stable GUI in a disposable directory with synthetic MIDI discovery and hardware activation blocked. It checks local import, Samples keyboard navigation/focus, preserved diagnostics, selected-file feedback, manifest persistence copy and bounds at the 1180×760 minimum. CI saves empty/selected workspace and editor screenshots under `docs/evidence/ux-2026-10-07`.
- Windows CI and independent review: pending candidate push and review. Native tests are deliberately not run on the user's desktop because native computer-use is unavailable; CI evidence must be reviewed before release.

## Limits

No device connection, physical MIDI acceptance, playback, audible-quality judgment, installer run or human usability study is claimed. This is a Windows desktop application; the test target is [the candidate source](https://github.com/generalgroovy/ko/tree/codex/ux-clarity-2026-10-07), launched with `python -m ko2_daw`. Release target remains [the main repository](https://github.com/generalgroovy/ko).
