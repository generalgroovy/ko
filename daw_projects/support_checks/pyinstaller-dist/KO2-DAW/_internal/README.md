# KO II Sampler DAW

Windows companion DAW, performance recorder, protocol lab, and integrity-safe
device explorer for the Teenage Engineering EP-133 / KO II.

The connected device was verified on **June 11, 2026** using a PC USB-A to
device USB-C data connection. Windows exposes it as both MIDI input and output
named `EP-133`.

Current verified device:

- Universal identity: `TE032AS001`
- Route: direct WinMM `EP-133 -> EP-133`
- File protocol chunk size: 512 bytes
- Device inventory: 816 records, 760 files, 56 visible directories
- Sound assets: 328 numbered `.pcm` files, 61,956,292 bytes total
- Project model: 9 project slots, each exposing groups A-D and 12 pad slots per group
- Latest inventory SHA-256:
  `fff10d5b1fefdd2754a26759c97e39a80261f5d6a26f9907a4383ec59daac940`

Device data integrity is the primary constraint. Read-only identity, file
listing, performance control, recording, and export are enabled. Destructive
device writes remain blocked until backup, write, read-back verification, and
rollback have all been proven against disposable data.

## Easiest Run On Windows

Double-click the stable launcher first:

```powershell
KO2-DAW-STABLE.bat
```

Stable mode is now the default. It installs the protocol monitor, MIDI
detection, communication panel, hardware explorer, state polling, performance
recorder, device library, and scene arranger.

The normal launcher also uses stable mode unless you explicitly opt into experimental mode:

```powershell
KO2-DAW.bat
```

## Experimental GUI Mode

The photo/device/timeline/matrix/segment-grid surface is preserved but opt-in:

```powershell
$env:KO2_DAW_GUI_MODE = "experimental"
python -m ko2_daw
```

or in CMD:

```cmd
set KO2_DAW_GUI_MODE=experimental
python -m ko2_daw
```

Use experimental mode only after stable mode launches correctly.

## Build A Windows Executable

Double-click or run:

```powershell
build_exe.bat
```

The built app appears at:

```text
dist\KO2-DAW\KO2-DAW.exe
```

You can copy the whole `dist\KO2-DAW` folder to another Windows machine. Keep the folder together; the `.exe` depends on the files beside it.

GitHub Actions also builds a downloadable Windows artifact named `KO2-DAW-windows` from `.github/workflows/build-windows-exe.yml`. Open the latest workflow run and download the artifact when the build completes.

## Run From Python

From this folder:

```powershell
python run_ko2_daw.py
```

or:

```powershell
python -m ko2_daw
```

or, after install:

```powershell
ko2-daw
```

The default launch opens a stable KO II desktop control app. It starts in dry-run mode. Use **CONNECT EP-133** in the GUI to switch the pads, transport, CC fader, and read-only hardware probes to the direct USB-C `EP-133` MIDI route.

For text-only startup status:

```powershell
python run_ko2_daw.py --status
```

Useful commands:

```powershell
python run_ko2_daw.py --list
python run_ko2_daw.py --doctor
python run_ko2_daw.py --usb-diagnose
python run_ko2_daw.py --ko2-route auto --note 36
python run_ko2_daw.py --init-session companion_session.json
python run_ko2_daw.py --note 60 --clock-ticks 2
python run_ko2_daw.py --cc 1 64
python run_ko2_daw.py --bank-msb 0 --bank-lsb 1 --program 2
python run_ko2_daw.py --monitor-input --monitor-seconds 10 --state-json daw_projects\ko2_state.json
python run_ko2_daw.py --sysex-probe self-test
python run_ko2_daw.py --sysex-probe identity
python run_ko2_daw.py --sysex-probe file-init
python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe identity --send-sysex-probe
python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe root-list --send-sysex-probe
python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe root-list --sysex-node 1000 --send-sysex-probe
python run_ko2_daw.py --capability-scan --capability-report-txt docs\ko2_device_interaction_capabilities.txt
python run_ko2_daw.py --capability-scan --capability-scan-live-actions --capability-report-txt docs\ko2_device_interaction_capabilities.txt
python run_ko2_daw.py --device-snapshot daw_projects\ep133_device_snapshot.json
python run_ko2_daw.py --list-audio-inputs
python run_ko2_daw.py --audio-capture daw_projects\audio_captures\take.wav --audio-input MAIN --audio-duration 10
python run_ko2_daw.py --audio-render-project daw_projects\audio_projects\song.json --audio-normalize
python run_ko2_daw.py --note 60 --save-project ko2_session.json
python -m ko2_daw.support_bundle
```

Live MIDI is intentionally opt-in:

```powershell
python run_ko2_daw.py --live --midi-backend winmm --ko2-route auto --note 36
```

Live mode requires both a visible output port and an allow-list match. On Windows, the app can use native WinMM for short MIDI messages and read-only SysEx without `python-rtmidi`. Write-capable SysEx operations remain blocked unless explicitly armed through the GUI communication profile.

## Support Bundles And Replayable Logs

Create a timestamped diagnostic ZIP:

```powershell
support_bundle.bat
```

or:

```powershell
python -m ko2_daw.support_bundle
```

The support bundle includes non-destructive diagnostics: MIDI report, readiness report, route decision, settings, Python/platform manifest, and optional local cache/state/capability files when present.

Protocol sessions can be serialized with `ko2_daw.protocol_recorder.ProtocolRecorder` and replayed with `ProtocolReplay`. This is intended for hardware-free regression tests of GUI/state parsing once a live session has been captured.

Support bundles include the latest device snapshot when available, so a bug
report can identify both the software configuration and the exact visible
device inventory without reading sample contents.

## Performance Recorder

The stable GUI now includes **DAW > Performance Recorder**. The physical-style
**REC** control opens and arms this recorder instead of only logging intent.

Implemented workflow:

- Capture MIDI generated by the app and MIDI observed from the EP-133.
- Record a fresh clip or overdub the current loop.
- Set clip BPM and loop length in beats.
- Quantize to 1/4, 1/8, 1/16, 1/32, or 1/64 with adjustable strength.
- Undo and redo destructive in-memory edits.
- Loop playback through the currently selected EP-133 MIDI route.
- Stop playback with explicit note-off cleanup for notes still held by the clip.
- Save/load an editable JSON performance clip using atomic file replacement.
- Export a format-0 Standard MIDI File for use in other DAWs.

The recorder stores musical timing in beats rather than wall-clock seconds.
Changing BPM therefore preserves the performance's musical placement.

## Scene Arranger

The stable GUI includes **DAW > Scene Arranger**, a four-track MIDI production
surface mapped to the KO II's groups and pad notes.

- Four group tracks: A `36-47`, B `48-59`, C `60-71`, D `72-83`.
- Eight scenes with an independent clip for every group.
- 4-128 step clips, per-step velocity, gate, and deterministic probability.
- Polymetric playback: shorter group clips repeat inside the longest scene clip.
- Per-track mute, solo, record arm, velocity scaling, and transpose.
- Per-clip MIDI CC automation points.
- Ordered song chain with scene repeats.
- Project-wide undo/redo and atomic JSON save/load.
- Type-1 Standard MIDI File export with separate group tracks.
- Import from the Performance Recorder, split automatically by KO II group.
- Record incoming EP-133 MIDI and app pad actions into armed clips.
- Master mode sends Start/Stop and 24 PPQN clock; follow mode advances from
  incoming device transport/clock; internal mode does not send clock.
- Playback tracks active notes and sends note-off cleanup on stop or error.

On June 11, 2026, a one-beat live arranger smoke test completed through native
WinMM to `EP-133`: Start, 24 clock ticks, note 36 on/off, and Stop. The device
did not echo short MIDI back to the input port.

## Audio Studio

The stable GUI includes **DAW > Audio Studio**, a non-destructive multitrack
audio timeline that complements the MIDI arranger and EP-133 sample library.

- Six initial audio tracks with add/remove, mute, solo, arm, gain, and pan.
- PCM WAV import from disk or immutable EP-133 device-library bundles.
- Timeline drag between tracks, beat-grid snap, edit cursor, split, duplicate,
  and source-preserving delete.
- Source-in/out trim, 0.125x-8x stretch, reverse, clip gain/pan, and fades.
- Waveforms in both the timeline and selected-source inspector.
- Project-wide undo/redo and atomic JSON save/load.
- Block-rendered stereo 16-bit WAV mixdown with resampling and optional
  normalization to -0.2 dBFS.
- Native WinMM recording from visible inputs without third-party audio
  packages. This machine exposes QUAD-CAPTURE `MAIN`, `1-2`, and `3-4`.
- **KO II BOUNCE** starts the MIDI arranger and 24-PPQN clock while recording
  the armed audio track, then trims pre-roll and imports the captured result.

Native capture and all audio edits are PC-side. They do not upload, delete,
move, or rewrite EP-133 files. A synchronized hardware bounce completed on June
11, 2026; the captured QUAD-CAPTURE signal was at its noise floor, so the MIDI
control/capture timing path is verified but the KO II analog output must still
be physically routed to the selected QUAD-CAPTURE input for audible audio.

## Integrity Snapshot

Capture the complete visible file tree without downloading or modifying device
file contents:

```powershell
python run_ko2_daw.py --device-snapshot daw_projects\ep133_device_snapshot.json
```

The snapshot records:

- Identity SKU and file-protocol chunk size.
- Every visible node id, parent node, path, kind, size, depth, and page.
- Directory/page request counts and scan-limit warnings.
- Aggregate file/directory counts and total visible sample bytes.
- A SHA-256 hash over the canonical sorted inventory.

The GUI exposes the same workflow under **Device > Capture Integrity
Snapshot**. It runs in the background using the already-open MIDI session and
saves `daw_projects\ep133_device_snapshot.json` atomically.

Use snapshots before and after any future write-capable experiment. A changed
hash is evidence that the visible inventory changed; it is not by itself a
content backup.

## Device Sample Library And Read-Only Backup

The stable GUI includes **Device Library > Open Device Sample Library** and a
**DEVICE LIBRARY** action in the local Samples tab.

The device library:

- Loads all 328 visible `/sounds/*.pcm` records from the live scan or latest
  integrity snapshot.
- Downloads a selected sound with the verified TE GET init/data protocol.
- Retrieves paged JSON metadata.
- Rejects unexpected pages, early termination, byte overflow, and declared-size
  mismatches.
- Computes SHA-256 and compares raw PCM CRC32 with the device metadata CRC.
- Converts supported PCM formats to standard WAV without changing the raw
  backup.
- Draws a local waveform and previews the WAV through Windows audio.
- Keeps EP-133 device audition available as a separate action.
- Registers exported WAV files in the existing 999-slot local sample library.
- Stores every distinct version in an immutable content-addressed bundle.

CLI example:

```powershell
python run_ko2_daw.py --device-download-node 207
```

Project directories also expose a read-only archive through the same GET
protocol. Use raw/no-metadata mode for a project node:

```powershell
python run_ko2_daw.py --device-download-node 3000 --device-download-no-metadata --device-download-raw-only
```

All nine project slots can be cataloged or backed up in one operation:

```powershell
python run_ko2_daw.py --device-project-catalog
python run_ko2_daw.py --device-project-backup-all
python run_ko2_daw.py --device-project-backup-all --device-project-backup-force
```

The stable GUI exposes the same workflow under **Projects > Open Project
Manager**. It verifies all local bundles, resumes by skipping valid slots,
refreshes all versions on request, opens pad maps, and compares any two projects.
The project inspector also lists every opaque binary record with hashes and a
hex preview. A selected pad can explicitly trigger the corresponding physical
EP-133 pad over notes 36-83; the UI warns that this auditions the device's
currently loaded project, which may differ from the archived project.

The June 11, 2026 capture verified every visible slot:

| Project | Node | Bytes | Pages | SHA-256 prefix | Assigned pads | Patterns | Files |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 01 | 3000 | 55,808 | 173 | `6437a3ac94d1` | 19 | 0 | 50 |
| 02 | 4000 | 138,752 | 429 | `4251de8ae6e7` | 35 | 62 | 113 |
| 03 | 5000 | 83,968 | 260 | `87d0721ebc08` | 42 | 21 | 72 |
| 04 | 6000 | 82,432 | 255 | `00568b4873fe` | 17 | 24 | 75 |
| 05 | 7000 | 74,240 | 230 | `7fa031d324b4` | 42 | 16 | 67 |
| 06 | 8000 | 112,640 | 348 | `8c91713ea519` | 19 | 55 | 105 |
| 07 | 9000 | 117,248 | 362 | `fb5918957d8d` | 36 | 56 | 107 |
| 08 | 10000 | 125,952 | 389 | `c5da9eaa0ebd` | 23 | 56 | 107 |
| 09 | 11000 | 65,024 | 201 | `014e86728122` | 37 | 8 | 59 |

`daw_projects/device_library/project_catalog.json` contains the full hashes,
paths, record sizes, and an aggregate content/structure hash. The current
catalog hash is
`dd8093f1f9edd327ebc4a4be9cf33b7cbad83666dc0571b3b6f5a1f5399290f6`.

Downloaded project TAR files are inspected without extracting members to disk.
The device uses lowercase, zero-padded paths `pads/{a-d}/p{01-12}`. All 48 pad
records are decoded; the sound id is a signed little-endian 16-bit value at
offset 1, where `0` is unassigned. Pattern records are indexed but remain
opaque. `fx_settings`, `scenes`, `settings`, patterns, and unknown files receive
SHA-256, CRC32, byte count, nonzero count, and a bounded preview without guessed
field labels. `scenes` is 712 bytes and `settings` is 222 bytes in all nine
captures. `fx_settings` is 160 bytes when present and is absent from Projects
01 and 06.

Project comparison reports changed pad sound ids and exact half-open byte ranges
for added, removed, or changed opaque records. Unsafe paths, duplicate paths,
links, malformed pad records, member-count overflow, per-member overflow, and
aggregate payload overflow are rejected.

Normal GUI disconnect, reconnect, scans, and close are blocked while a device
download is active. A project batch advances only after the current stateful
GET has consumed every declared byte.

## Current USB/MIDI Distinction

- If `ko2_usb_connected` is `True`, Windows can see the EP-133 over USB.
- If `ko2_midi_ready` is `False`, Windows has not exposed the EP-133 as a MIDI input/output port, so this MIDI app cannot send directly to it yet.
- `--usb-diagnose` prints the exact USB classes. Direct USB MIDI normally requires a MIDI streaming interface, not only USB Audio Control.
- `--ko2-route auto` resolves the best available route. With a direct USB-C MIDI connection it selects `EP-133`.
- Run `python run_ko2_daw.py --list` after changing cable, USB mode, firmware, or drivers.

The connector shape at the computer does not change the protocol. A USB-A to
USB-C data cable works when Windows exposes the EP-133 MIDI streaming
interfaces. A charge-only cable does not.

## State Monitoring

- The app can infer transport, clock, active notes, program changes, bank select, mod wheel, and observed controllers from incoming MIDI.
- The public EP-133 MIDI implementation does not provide a full query/dump for current project, sample names, selected effect, or complete front-panel state. Those fields are shown as unknown unless MIDI traffic exposes them.
- In experimental mode, the segment grid models A1-A99, B1-B99, C1-C99, and D1-D99 as occupied, empty, selected, or unknown.

Short MIDI commands are acted on by the device but were not echoed during the
June 11 probe. Consequently:

- App-originated state is known because the DAW sent it.
- Physical-device state is known only when the EP-133 transmits corresponding MIDI.
- Unobserved front-panel state remains `unknown`, not guessed.
- Timeline/project views label inferred events as inferred evidence.

## Companion Sessions

- `--init-session companion_session.json` creates a professional session file with the EP-133 profile, 48 pad assignments, routing placeholders, supported MIDI controls, and unsupported state-query notes.
- The GUI `SAVE SESSION` button writes `daw_projects\companion_session.json`.
- The GUI `DOCTOR` button reports whether the connected EP-133 is USB-only or MIDI-ready.

## Windows Shortcuts

Double-click or run:

```powershell
KO2-DAW-STABLE.bat
KO2-DAW.bat
support_bundle.bat
ko2-daw.cmd
launch_ko2_daw.cmd
test_ko2_daw.cmd
```

Usability aids:

- Hover over controls for tooltips explaining what each interaction does.
- Use **Protocol Monitor** for app/device traffic.
- Use **Communication Panel** for connection/profile/access settings.
- Use **MIDI Detect** for EP-133 port diagnostics.
- Use **Configuration > Save Settings** to persist app-level connection and access policy choices.

The current probe summary is saved in `docs\ko2_device_interaction_capabilities.txt`.

On launch, the GUI checks the configured route automatically. If it finds a usable EP-133/KO II MIDI route, it asks for confirmation before opening live MIDI. If no route is usable, it stays in dry-run mode and logs the route status.

## SysEx Lab

This project ports the safe protocol primitives from `generalgroovy/ko2` branch `codex/ko2-sysex-lab`:

- TE manufacturer SysEx frame build/parse.
- 7-bit payload pack/unpack.
- Universal identity request/parser.
- Read-only file protocol payloads for init, list, info, and metadata get.
- Explicit file playback start/stop payload for selected hardware rows.
- File list and JSON metadata response parsers.
- Write-capable file operations blocked by default; expert-write/full-lab profiles can arm low-level frame construction only after typing `WRITE`, and destructive write buttons are still not exposed.

The app can generate, send, receive, and parse identity/file probes over the direct USB-C `EP-133` MIDI route. Hardware browsing remains read-only unless the app is configured for selected-file playback preview. It does not expose upload, delete, move, restore, or metadata-write buttons.

### Verified File Protocol

The confirmed read-only exchange uses:

- Universal identity request: `F0 7E 7F 06 01 F7`
- Teenage Engineering manufacturer id: `00 20 76`
- TE file command wrapper: command `5`
- File init subcommand: `1`
- File list subcommand: `4`
- File playback subcommand: `5`, actions start `1` and stop `2`
- File GET subcommand: `3`, init type `0`, data type `1`
- Metadata GET subcommand: `7`, action `2`
- 7-bit packed SysEx payloads
- 14-bit request identifiers
- Response matching by command and request id; unrelated firmware log SysEx is
  ignored

Verified node 207 download:

- `/sounds/207.pcm`, 3,988 bytes
- 13 pages: 12 x 324 bytes plus 100 bytes
- mono signed 16-bit PCM at 46,875 Hz
- CRC32 `2251392378`, matching device metadata
- SHA-256
  `a6776d9fc2fded058e33c98874b7ce51eede2f6eea71b6edd9968f506899befd`

See [docs/ep133_file_protocol.md](docs/ep133_file_protocol.md) for the exact
request/response layouts and transaction-safety findings.

If the device reports `err lfs 6327 2_0_5`, an earlier manual GET transaction
was abandoned. Reconnect or power-cycle the EP-133 before retrying. The
integrated downloader prevents normal app close/disconnect during a transfer to
avoid creating this condition.

Confirmed root nodes:

| Node | Path | Meaning |
| ---: | --- | --- |
| 0 | `/` | File-protocol root |
| 1000 | `/sounds` | Numbered PCM sample assets |
| 2000 | `/projects` | Project slots |

Confirmed project node pattern:

- Project directories: `01` through `09`, nodes 3000 through 11000.
- Each project contains `/groups`.
- Each `/groups` contains `A`, `B`, `C`, and `D`.
- Each group exposes virtual pad-slot files `01` through `12`.
- These project pad-slot nodes report size zero through LIST; they behave as
  assignments/references rather than sample-content files.
- Sound content lives under `/sounds/NNN.pcm`; the current unit exposes 328
  populated sound nodes.

The largest currently visible sound is `/sounds/007.pcm` at 2,950,332 bytes.
Several sound slots contain 1,875,000-byte PCM assets. The LIST protocol
reports stored byte sizes but does not itself disclose sample rate, channel
count, bit depth, loop points, envelope, or pad parameters.

### Verified MIDI Control

| Area | Verified behavior |
| --- | --- |
| Pads | Notes 36-47 group A, 48-59 B, 60-71 C, 72-83 D |
| Transport | MIDI Start, Continue, Stop |
| Clock | MIDI timing clock messages accepted |
| Fader | CC 1 |
| Bank | CC 0 and CC 32 |
| Program | Program Change accepted |
| Safety | CC 123 All Notes Off and CC 120 All Sound Off |

The device did not echo these short messages during controlled probes. A
separate generic SysEx query for current project, selected pad, effect,
front-panel mode, or full pattern data has not been identified.

### Write Safety Boundary

The protocol reference contains PUT, DELETE, MOVE, metadata-write, and
playback operations. Only playback start/stop is exposed as an explicit,
non-persistent action. Persistent writes remain blocked because a safe write
feature requires all of the following:

1. Readable source content and metadata.
2. A complete pre-write inventory snapshot.
3. A content backup, not only a directory listing.
4. Exact target-node and payload validation.
5. Post-write read-back and checksum verification.
6. A tested rollback path.

Typing `WRITE` in an expert communication profile currently arms low-level
frame construction for protocol research; it does not expose destructive GUI
commands.

## Development Architecture

GUI extensions are installed by a declarative plugin registry in `ko2_daw.gui_plugins`. Stable mode installs only conservative extensions. Experimental mode enables the unstable custom hardware surface work for further iteration.

Core device logic is kept outside Tkinter:

- `device_snapshot.py`: reusable read-only inventory capture and integrity hash.
- `performance.py`: beat-based recorder, quantize, history, playback, and MIDI export.
- `protocol_recorder.py`: raw protocol event serialization and hardware-free replay.
- `sysex_exchange.py`: decoding and individual safe probe exchange.
- `te_sysex.py`: frame packing, parsing, file payloads, and write policy.

## Optional Install

The app has no required third-party dependency for dry-run use or native Windows WinMM short MIDI output. For the optional mido backend:

```powershell
python -m pip install mido python-rtmidi
```

## Test

```powershell
python -m pytest
python -m pytest tests/test_protocol_recorder.py tests/test_support_bundle.py tests/test_gui_plugins.py tests/test_stable_imports.py
```
