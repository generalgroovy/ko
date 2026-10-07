# KO II: a clearer local workspace

Base: `2df8c2609f605699ef72b618cd8be0db94fcd602` (`origin/main`). Candidate branch: `codex/ux-clarity-2026-10-07`. All ten pre-existing untracked pytest directories are preserved. Main and deployment remain owned by the lead.

## Changes

The former prominent Library card opened the connected-device library, while the local Samples workflow had no home action. Home now groups Samples, Compose, Audio and Perform separately from Device Files, Device Library, Projects and Settings. Cards are native buttons with visible keyboard focus, Space and Enter activation. Samples returns directly to Import WAV when empty, or focuses the populated table. Less frequent MIDI detection, protocol inspection and communication controls remain in Tools.

Samples starts with a concrete import instruction and changes to the selected file's name. Trim/slice follows import in the action order. Open Library and Save Library describe their purpose in ordinary language, with adjacent copy explaining that JSON keeps file references, not audio. Format details reveals the secondary technical columns; both scrollbars preserve access to long lists and paths. MIDI triggering remains distinct from local playback and retains the existing routing gate.

The editor keeps exact numeric precision and keyboard frame adjustment. Reading or saving disables the range inputs; cancellation recovers them after the worker finishes. Select all names the full-range reset. A failed or cancelled initial read offers Retry read. The idle Cancel button becomes Close. Completed exports show a selectable full output-folder path, separate from the brief completion status. PCM writing, frame partitioning, original-file preservation and atomic library insertion are unchanged. Root visual review found clipped hardware legends inside the supported studio window; wider function columns and less decorative padding now keep COMMIT, CORRECT, SYSTEM, RECORD and FADER readable without reducing font sizes or removing controls.

## Validation

- Local Windows/Python 3.14: `python -m pytest -q -rs --basetemp=C:/Users/sende/AppData/Local/Temp/ko-ux-20261007-tests` — **215 passed, 1 skipped**. Existing symlink test needs platform permission.
- Ruff, Black check, compilation and diff whitespace passed.
- `tools/check_sample_editor_ui.py` extends the real Tk checks with locked ranges, cancellation recovery, output location, retry after fixing a malformed source and idle Close. Existing exact PCM, keyboard and 680/460-pixel checks remain.
- `tools/check_workspace_ui.py` constructs the complete stable GUI in a disposable directory with synthetic MIDI discovery and hardware activation blocked. It checks local import, Samples keyboard navigation/focus, preserved diagnostics, selected-file feedback, manifest persistence copy and bounds at the 1180×760 minimum. CI saves empty/selected workspace and editor screenshots under `docs/evidence/ux-2026-10-07`.
- The first composed-GUI run exposed a pre-existing startup failure: the device-library plugin packed a redundant Device Library button into the Samples toolbar, whose controls use grid. Removing that duplicate injection restores startup; the Device Library card remains available. The new full-composition test covers the plugin interaction.
- Final runtime: `0f721da247a28b3e323dc781160d8c1f601977bc`. [CI 37602958883](https://github.com/generalgroovy/ko/actions/runs/37602958883) passed both jobs: Windows **215 tests, 1 existing skip**, lint/format/compile and both Tk harnesses; complementary Linux/Xvfb complete-workspace interactions and screenshots.
- [Windows editor results](evidence/ux-2026-10-07/0f721da/windows/results.json), [Windows composed-workspace results](evidence/ux-2026-10-07/0f721da/windows/workspace-results.json), [460-pixel editor](evidence/ux-2026-10-07/0f721da/windows/sample-editor-460.png), [saved-folder feedback](evidence/ux-2026-10-07/0f721da/windows/sample-editor-saved.png).
- [Linux/Tk complete workspace results](evidence/ux-2026-10-07/0f721da/linux/workspace-results.json), [empty workspace](evidence/ux-2026-10-07/0f721da/linux/workspace-empty.png), [selected file and readable hardware legends](evidence/ux-2026-10-07/0f721da/linux/workspace-selected.png). Both platforms assert that every hardware legend plus padding fits its actual button using Tk font measurements.
- The Windows CI desktop is smaller than the full studio. Earlier whole-window screenshots and window-handle captures were clipped/blank and are not accepted visual evidence. Windows widget interactions remain valid; complete whole-workspace rendering is checked separately on Linux/Tk with a 1600×1000 virtual screen. Windows whole-home visual acceptance is not claimed.
- Independent reviewer `ux_midi` accepted the source behavior, cancellation/recovery and editor rendering without a blocking finding. Root then found the hardware-label clipping described above. The corrected runtime passes both platforms and its new screenshot has been inspected by the owner; final integration/rendered acceptance belongs to the lead. No native tests ran on the user's desktop.

## Limits

The full studio preserves its established **1180×760** minimum and needs additional desktop space for borders/taskbar. **1024×768 is not supported by the fixed side-by-side studio layout**. A larger CI display captures that supported layout; it does not establish small-screen usability. Only the separate sample editor was tested at 460×390. A responsive full-studio reflow remains future work.

No device connection, physical MIDI acceptance, playback, audible-quality judgment, installer run or human usability study is claimed. This is a Windows desktop application; the test target is [the candidate source](https://github.com/generalgroovy/ko/tree/codex/ux-clarity-2026-10-07), launched with `python -m ko2_daw`. Release target remains [the main repository](https://github.com/generalgroovy/ko).
