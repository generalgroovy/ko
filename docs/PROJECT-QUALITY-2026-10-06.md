# KO II sample workbench iteration

## Plan and acceptance

Baseline: `db9a0514a0f4873817ffd8bacda7183dcea8c0f5` (main). Existing untracked pytest output directories are preserved.

The primary local journey is import a WAV, select useful audio, save a new copy and keep it in a reusable library. The existing trim dialog exports only one region, gives no exact frame feedback and cannot cancel a long waveform read. Build on that dialog: direct edge selection and keyboard adjustment, concise selection feedback, optional equal slices for rhythmic/chopped material, cancellable background operations and atomic library insertion.

Acceptance: 8/16/24/32-bit PCM remains exact, the original never changes, slice boundaries partition the selected frames without gaps or overlap, failed/cancelled exports leave no owned partial outputs, existing destinations are preserved, and closing during a write waits for worker completion. Real Tk checks run on Windows CI; sample editing tests use synthetic audio only. No device connection, audio playback, driver changes or physical acceptance is performed.

## Results

The existing **TRIM COPY** entry opens the improved editor. One export choice defaults to a single copy and offers 2/4/8/16 slices. The waveform shows the selected range, slice boundaries and order. Seconds and exact frame count remain visible. Left/Right changes one frame, Shift changes 10 ms, and Home/End moves the active edge to its available boundary. Numeric input is validated before export. Exact seconds are retained internally and in the entry; the shorter duration summary is descriptive only.

Exports preserve rate, width, channels and selected PCM bytes. An odd frame count is divided into slices differing by at most one frame. Slice output uses a newly created folder; a failure or Cancel removes completed and partial files belonging to that operation, preserving unrelated files added by another process. Library insertion validates the full batch before changing any rows. Capacity or late file-read failures keep the saved WAVs available and explain that the library was unchanged. Closing during a write remains guarded; closing an idle editor also cancels its remaining waveform read.

Self-review corrected two findings: bare truncated-header errors could show an empty message, and dense peaks could obscure slice shading. The editor now gives a readable incomplete-WAV explanation and draws contrasting selection edges, separators and indices above the waveform. Parent review caught overlapping index badges on very short slices; indices now appear only when each slice has enough display width, with a 48-frame/16-slice native regression. The first native test run also exposed a harness comparison against Tk's state object; native `instate()` checks replaced the comparison without removing action/layout assertions.

## Validation and evidence

- **Local, Windows/Python 3.14:** `python -m pytest -q -rs --basetemp=<unique temporary folder>` — **215 passed, 1 skipped**. The skipped existing migration test requires symlink creation permissions. Compilation, Ruff 0.16.9, Black 26.5.1, diff whitespace and strict UTF-8 decoding passed.
- **Model tests:** all PCM widths in mono/stereo, each slice count, independently enumerated frame partitions, byte-identical concatenation and original preservation; invalid ranges; existing destinations; late truncation; cancellation at five distinct checkpoints; large-file chunk cancellation; unrelated-file preservation; full/invalid library batches; GUI EOF/missing-file recovery; one-frame 44.1/48/96/192 kHz round trips.
- **Windows/Python 3.11 CI:** [first complete interaction pass](https://github.com/generalgroovy/ko/actions/runs/37543645930) — **215 passed, 1 skipped**, compile/lint/format pass, real Tk 680/460-pixel windows. [Retained first-pass results](evidence/sample-editor-2026-10-06/results.json) and screenshots document the dense-peak visibility finding before its correction.
- **Final runtime:** `a02db3b899cb4cc99cd16f6f2b1b062184bd91f8`. [Final CI](https://github.com/generalgroovy/ko/actions/runs/37544147447) — **PASS**, including 215 tests/1 skip, compilation, lint, formatting and the expanded native Tk interactions. [Final results](evidence/sample-editor-final-2026-10-06/results.json), [460-pixel screenshot](evidence/sample-editor-final-2026-10-06/sample-editor-460.png) and [680-pixel screenshot](evidence/sample-editor-final-2026-10-06/sample-editor-680.png) were downloaded and visually reviewed.
- **Windows package build:** [run 37544147959](https://github.com/generalgroovy/ko/actions/runs/37544147959) — **PASS** at that same runtime, including tests, PyInstaller and artifact upload. This proves packaging; the produced executable was not installed or launched here.

Run from source with `python -m ko2_daw`, then Samples → IMPORT WAV → TRIM COPY. Reproduce the synthetic Windows UI checks with `python tools/check_sample_editor_ui.py` after installing Pillow. CI uploads `ko-sample-editor-ui`; the package workflow uploads `KO2-DAW-windows`.

## Limits and release boundary

No audible output, EP-133 device session, installer execution or human usability study was performed. Exact slices apply no fades or zero-crossing shifts, so boundaries may click; this is explained in Info and README. Cancellation is cooperative between bounded frame chunks. The original ten untracked pytest output directories are untouched. The candidate branch is `codex/ko-sample-slicing-depth`; main promotion and public catalogue integration belong to the parent review.
