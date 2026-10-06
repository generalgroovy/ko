# KO II sample workbench iteration

## Plan and acceptance

Baseline: `db9a0514a0f4873817ffd8bacda7183dcea8c0f5` (main). Existing untracked pytest output directories are preserved.

The primary local journey is import a WAV, select useful audio, save a new copy and keep it in a reusable library. The existing trim dialog exports only one region, gives no exact frame feedback and cannot cancel a long waveform read. Build on that dialog: direct edge selection and keyboard adjustment, concise selection feedback, optional equal slices for rhythmic/chopped material, cancellable background operations and atomic library insertion.

Acceptance: 1–32-bit PCM formats remain exact (supported WAV widths are 8/16/24/32-bit), the original never changes, slice boundaries partition the selected frames without gaps or overlap, failed/cancelled exports leave no owned partial outputs, existing destinations are preserved, and closing during a write waits for worker completion. Real Tk checks run on Windows CI; local tests use synthetic audio only. No device connection, audio playback, driver changes or physical acceptance is performed.

## Results

Implementation and validation in progress. Evidence will distinguish local automated checks, target CI and untested hardware/audio behavior.
