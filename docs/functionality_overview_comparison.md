# KO II Companion Functionality Overview and Comparison

Updated: 2026-06-11

References:
- Live web app: https://generalgroovy.github.io/ko2/
- Reference branch previously inspected: https://github.com/generalgroovy/ko2/tree/codex/ko2-sysex-lab
- Current Python project: C:\Users\sende\Documents\KO-2

## Current Hardware Reality

The KO II / EP-133 is connected directly to this Windows machine through USB-C and is visible at the USB/device level.

Current Python report:

- `ko2_usb_connected`: true
- USB device: `VID_2367&PID_0020`
- Friendly USB interface: `EP-133`
- Windows service: `usbaudio`
- `ko2_midi_ready`: true after direct USB-C reconnection
- visible MIDI input ports: `QUAD-CAPTURE`, `EP-133`
- visible MIDI output ports: `Microsoft GS Wavetable Synth`, `QUAD-CAPTURE`, `EP-133`
- native Windows MIDI backend: available through WinMM
- best app route: `usb-midi-ready`
- route input: `EP-133`
- route output: `EP-133`
- USB-C direct retest: EP-133 appears as a WinMM MIDI input/output named `EP-133`.

Interpretation:

- The EP-133 is physically connected and detected by Windows.
- Windows now exposes it as a MIDI input/output endpoint named `EP-133`.
- Direct remote control of the KO II over USB MIDI is ready through the Python app, with live sends still requiring explicit `--live`.
- The Python app can control any visible MIDI output through native WinMM, with live sends gated by `--live`, output-port selection, and allow-list matching.
- Read-only SysEx over direct USB-C is verified:
  - universal identity returns `TE032AS001`
  - file init returns a 512-byte chunk size
  - root list returns `sounds` node `1000` and `projects` node `2000`
  - listing `sounds` returns 21 sample PCM entries
  - listing `projects` returns 9 project entries

## Python Project Overview

The Python project is an install-free Windows desktop/CLI companion app with conservative hardware safety.

### Launch and Interface

- `python run_ko2_daw.py`
- `python -m ko2_daw`
- `ko2-daw.cmd`
- `launch_ko2_daw.cmd`
- `test_ko2_daw.cmd`
- Tkinter GUI resembling the EP-133 / KO II control layout.
- Text-only status mode: `--status`.

### Device and MIDI Discovery

- Lists MIDI input/output ports.
- Detects native WinMM availability.
- Detects `mido` / `rtmidi` availability.
- Detects connected USB devices from the Windows registry.
- Specifically identifies `VID_2367&PID_0020` as EP-133 / KO II USB presence.
- Separates `ko2_usb_connected` from `ko2_midi_ready`.
- Saves device reports as JSON with `--report-json`.
- Provides device readiness diagnostics with `--doctor`.

### Remote MIDI Control

Implemented:

- Note on/off test with `--note`.
- MIDI clock ticks with `--clock-ticks`.
- Start/stop transport through controller methods.
- Program change with `--program`.
- Bank select with `--bank-msb` and `--bank-lsb`.
- Control change with `--cc CONTROL VALUE`.
- Panic/all-notes-off/all-sound-off.
- Native Windows WinMM output backend.
- Optional `mido` backend.
- Dry-run backend for safe testing and unit tests.
- Live output safety:
  - dry-run by default
  - live mode requires `--live`
  - live mode requires explicit port selection or an unambiguous allow-list match
  - SysEx blocked by default in the high-level controller

Verified with the current direct USB-C connection:

- Direct KO II USB MIDI control through `EP-133`.
- Read-only SysEx identity and file-list probes through `EP-133` input/output.

### MIDI Input and State Monitoring

Implemented:

- Native WinMM input monitor.
- `--monitor-input`.
- `--monitor-seconds`.
- `--state-json`.
- `--capability-scan`.
- `--capability-scan-live-actions`.
- `--capability-report-txt`.
- Inferred runtime state:
  - transport: unknown / playing / stopped / clock seen
  - active notes
  - clock tick count
  - program change
  - bank select MSB/LSB
  - mod wheel
  - observed controllers
  - recent MIDI events
- GUI state strip for transport, active notes, clock, and mod wheel.

Known limitation:

- The public EP-133 MIDI behavior does not provide a full query/dump for current project, sample names, selected effect, pattern content, or complete front-panel state. The Python app therefore labels those as unknown unless MIDI traffic exposes them.

### EP-133 Profile and Companion Sessions

Implemented:

- `DeviceProfile`.
- `PadAssignment`.
- `RoutingConfig`.
- `CompanionSession`.
- `CompanionSessionStore`.
- Default EP-133 profile:
  - Group A notes `36-47`
  - Group B notes `48-59`
  - Group C notes `60-71`
  - Group D notes `72-83`
  - 48 pad assignments
  - supported controls list
  - unsupported state-query list
- `--init-session companion_session.json`.
- GUI `SAVE SESSION`.
- Atomic JSON session writes.

### Project Storage

Implemented:

- `ProjectSnapshot`.
- Atomic JSON saves.
- Backup-on-overwrite behavior.
- Project path traversal rejection.
- GUI dry-run session save.

### Sequencer and Performance Primitives

Implemented:

- Deterministic beat-based `StepSequencer`.
- `StepEvent`.
- Note-on/note-off rendering.
- GUI pad trigger grid.
- GUI GROUP A-D selection.
- GUI velocity control.
- GUI BPM control.
- GUI fader mapped to CC 1 / mod wheel.
- GUI transport controls.

### SysEx Lab

Implemented from `generalgroovy/ko2` `codex/ko2-sysex-lab` reference:

- Teenage Engineering manufacturer SysEx constants.
- TE frame build/parse.
- 7-bit SysEx payload packing/unpacking.
- Universal identity request/parser.
- TE echo frame generation.
- Read-only file protocol payloads:
  - file init
  - root/list
  - root/info
  - metadata get
- Response parsers:
  - file init response
  - file list response
  - JSON metadata response
  - TE metadata string
- Status text mapping.
- Write-capable file operations blocked:
  - PUT
  - DELETE
  - MOVE
  - PLAYBACK
  - metadata writes
- CLI:
  - `--sysex-probe self-test`
  - `--sysex-probe identity`
  - `--sysex-probe te-echo`
  - `--sysex-probe file-init`
  - `--sysex-probe root-list`
  - `--sysex-probe root-info`
  - `--sysex-probe metadata-get`
- GUI `SYSEX LAB` button.

Implemented after direct USB-C verification:

- Sending read-only SysEx probes to live hardware.
- Awaiting and parsing SysEx responses.
- File tree rows generated from real hardware root/sounds/projects lists.

Current transfer boundary:

- Sample download, metadata retrieval, CRC/SHA-256 verification, PCM-to-WAV
  export, waveform display, and local preview are implemented.
- All nine project archives are downloaded and integrity verified. The project
  manager catalogs 9/9 slots, resumes missing backups, refreshes all versions,
  opens decoded pad maps, and compares pad assignments plus exact changed byte
  ranges in opaque project records.
- Project records include 48 pad files, optional 160-byte `fx_settings`,
  variable pattern files, 712-byte `scenes`, and 222-byte `settings`. Only the
  verified pad sound-id field is semantically decoded.
- Sample upload, project restore, delete, move, and metadata writes remain
  blocked.

Write operations are intentionally blocked until backup/download semantics are verified.

### Tests

Current test coverage:

- Controller safety.
- Dry-run MIDI sends.
- Live output allow-list enforcement.
- SysEx blocking.
- Sequencer rendering.
- WinMM short-message packing/parsing.
- Runtime state inference.
- Atomic project store.
- Companion session store.
- Default EP-133 profile.
- GUI pad note ranges.
- CLI validation.
- CLI CC/program dry-run output.
- USB-only readiness report.
- TE SysEx packing, frame parsing, identity parser, file payloads, write blocking.
- Project TAR path safety, opaque record fingerprints, byte-range comparison,
  catalog integrity, tamper detection, and resumable backup.

Current result:

- `python -m pytest -q`
- The suite covers controller safety, protocol matching, device snapshots,
  performance recording, file download integrity, WAV export, and GUI plugin
  construction.

## generalgroovy.github.io/ko2 Overview

The web app is a browser-based Web MIDI / SysEx lab and sample-management style interface.

Visible functionality from the live app:

- Web MIDI connect and refresh.
- MIDI diagnostics.
- Separate input and output selectors.
- Play mode:
  - local + MIDI
  - MIDI only
  - local only
- Performance controls:
  - channel
  - base note
  - velocity
  - gate time
  - hold notes until panic/stop
  - computer keyboard triggers pads
- Panic.
- MIDI clock controls:
  - continue
  - tick
  - stop
- Runtime settings:
  - request SysEx privilege
  - retry SysEx after MIDI registration
  - auto-select KO II ports
  - listen to selected MIDI input
  - enable read-only probes
  - show write privileges as unlocked
  - log unmatched MIDI input
  - auto-load project after connect
  - device ID
  - probe timeout
  - port poll attempts
  - port poll interval
  - recursive scan depth
  - PCM sample rate
  - PCM channels
  - PCM bit depth
- Read probes:
  - identity
  - TE echo
  - file init
  - root info
  - list root
  - list sounds
  - list projects
  - sounds metadata
  - projects metadata
- Local file area:
  - drop audio / PCM / JSON
  - manifest export
  - compare
  - all WAV export
  - selected WAV export
- Write privilege surface:
  - upload
  - delete
  - move
  - metadata
  - device play
  - backup
  - these are surfaced but guarded in the reference branch by write-lock controls.
- Device strip:
  - input
  - output
  - port counts
  - device ID
  - SKU
  - serial
  - file chunk
  - SysEx state
  - privileges
- Live monitor:
  - observed state
  - MIDI input
  - MIDI output
  - SysEx/file state
  - held notes
  - clock
- Timeline with play/stop and time display.
- Samples table:
  - 999 slot awareness
  - slot
  - pad
  - name
  - kind
  - duration
  - rate
  - size
  - waveform
  - audio
  - actions
- Project view:
  - scenes
  - tracks
  - pads
  - group A-D filtering
  - local + MIDI / MIDI / local pad actions
- Hardware view:
  - scan
  - export
  - clear
  - cached device folders
- Function queue.
- Session log export/clear.

Additional functionality from the referenced branch README/protocol notes:

- Plain MIDI registration before SysEx upgrade.
- TE SysEx frame helpers.
- 7-bit payload packing/unpacking.
- Universal identity parsing.
- Teenage Engineering identity reply parsing.
- File protocol init/list/info/metadata probes.
- Cached tree export.
- Local-vs-device sample comparison.
- Imported manifest rendering for samples, scenes, tracks, pads, and clips.
- Raw `.pcm` / `.raw` import with configurable sample rate, channels, and bit depth.
- Browser audio decode and waveform preview.
- WAV export.
- Protocol log export.
- Write-capable operations blocked by default unless explicitly enabled in code/settings.

## Comparison

| Area | Python project | generalgroovy web app |
| --- | --- | --- |
| Runtime | Native Python desktop/CLI | Browser Web MIDI app |
| Out-of-box install | No package install for dry-run/WinMM | Browser only, requires Web MIDI-capable browser |
| UI | Tkinter KO II-style control surface plus full scene arranger | Dense EP Sample Tool-style web workspace |
| MIDI discovery | WinMM, optional mido, Windows USB registry | Web MIDI API |
| Current EP-133 detection on this PC | USB and direct MIDI endpoint ready as `EP-133` | Must be tested in Chrome/Edge with Web MIDI permission |
| Native Windows MIDI | Yes, WinMM short messages | Browser abstracts MIDI |
| MIDI output control | Notes, CC, program, bank select, clock, panic | Pads, performance controls, clock, panic |
| MIDI input monitor | Yes, WinMM input monitor | Yes, Web MIDI input listener |
| Runtime state | Inferred state object and JSON export | Live observed state cards/timeline |
| Full KO II state read | Not available unless MIDI/SysEx exposes it | Not available except through read-only SysEx probes/cache |
| SysEx protocol helpers | Yes, ported to Python | Yes, original JavaScript implementation |
| SysEx live send | Identity/file probes and explicit selected-file playback preview over WinMM | Web MIDI SysEx send/probe surfaces |
| File tree scanning | Automatic recursive device tree load on connection, selected-node refresh, cache/export from GUI | Read-only scan/cache UI |
| Sample import/playback | Local WAV import, preview, manifest, MIDI trigger, multitrack timeline | Local audio/PCM import, preview, waveform |
| WAV export | Downloaded PCM export plus block-rendered stereo multitrack mixdown | All/selected local WAV export |
| Manifest/project import | Arrangement/performance/session JSON; nine-slot project TAR catalog, pad map, binary inventory, and structural diff | JSON manifest import for samples/scenes/tracks/pads |
| Sample slot table | 999-slot local WAV table | 999-slot sample table |
| Local-vs-device comparison | Device library marks RAW/WAV availability and verified hashes per device node | Implemented for cached device tree/local samples |
| Backup/restore | Immutable sound backup; all nine project TARs verified with resumable catalog and versioned refresh; restore blocked | UI target/surface; write operations guarded |
| Arranger | Four tracks, eight scenes, polymetric clips, probability, CC automation, song chain, capture, clock master/follow, type-1 MIDI export | Basic performance and manifest surfaces; no equivalent tested native arranger |
| Audio timeline | Multitrack PCM WAV clips, native input recording, trim/split/stretch/reverse/fades/mixer, normalized render, synchronized KO II bounce | Local sample preview/export, not a tested multitrack native DAW |
| Write operations | Upload/delete/move/metadata writes blocked; selected-file playback start/stop allowed explicitly | Guarded/blocked by default in reference branch |
| Tests | Python pytest suite covering hardware safety, protocol, DAW, and GUI modules | No local test suite observed in static web app files |

## Functionality Missing From Python Project Compared To Web App

High-value gaps:

1. Drag/drop or file picker import for AIFF/PCM/RAW.
2. Ten-bank browser around the 999-slot sample table.
3. General JSON manifest import for external scenes/tracks/pads/clips.
4. AIFF/FLAC/MP3 decoding and high-quality phase-vocoder time-stretch.
5. Hash-based local-vs-device comparison across an entire library.
6. A persistent background operation queue with pause/resume.
7. Decoding independently verified fields inside project `scenes` and
   `settings` records.
8. Verified restore with preflight backup, read-back comparison, and rollback.

## Functionality Present In Python Project But Not Central In Web App

1. Native Windows USB registry detection for EP-133.
2. Clear distinction between USB-visible and MIDI-ready.
3. Native WinMM backend without browser/Web MIDI.
4. Install-free Windows `.cmd` launch scripts.
5. Atomic project/session JSON writes.
6. Backup-on-overwrite for project snapshots.
7. Unit-tested safety gates.
8. Companion session/profile dataclasses.
9. Path traversal rejection for project/session stores.
10. CLI-first hardware diagnostics that work outside a browser.
11. Automatic recursive hardware file tree load on GUI connection.
12. Selected hardware sound/track file playback preview from the native GUI.
13. Native four-group scene/song arranger with MIDI clock master and follower.
14. Safe in-memory EP-133 project TAR parser and pad-to-sound inspector.
15. Native WinMM multitrack recording and a non-destructive audio timeline.
16. Synchronized EP-133 MIDI arranger-to-audio bounce through QUAD-CAPTURE.

## Required Direction So Python App Can Control The Connected KO II

The current direct USB-C connection exposes an EP-133/KO II MIDI input/output endpoint. If this changes, the operating system must expose that endpoint before direct control can work.

Immediate verification path:

1. Run:
   ```powershell
   python run_ko2_daw.py --list --report-json daw_projects\usb_midi_report.json
   python run_ko2_daw.py --doctor
   python run_ko2_daw.py --usb-diagnose
   python run_ko2_daw.py --ko2-route auto --note 36
   ```
2. If `ko2_midi_ready` remains false, try:
   - reconnecting the KO II directly to the PC without a hub
   - another USB data cable
   - a different USB port
   - closing any app that may hold the MIDI endpoint
   - checking the KO II USB/MIDI mode and firmware
   - checking whether Chrome/Edge Web MIDI sees an EP-133 port at https://generalgroovy.github.io/ko2/
   - routing KO II DIN MIDI through `QUAD-CAPTURE`
3. With direct USB-C MIDI ready, dry-run first:
   ```powershell
   python run_ko2_daw.py --ko2-route usb-midi --note 36
   ```
4. To intentionally trigger the sampler live:
   ```powershell
   python run_ko2_daw.py --live --midi-backend winmm --ko2-route usb-midi --note 36
   ```
5. To monitor incoming MIDI:
   ```powershell
   python run_ko2_daw.py --monitor-input --input-port "EP-133" --monitor-seconds 30 --state-json daw_projects\ko2_state.json
   ```
6. Verified read-only SysEx probes:
   ```powershell
   python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe identity --send-sysex-probe
   python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe root-list --send-sysex-probe
   python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe root-list --sysex-node 1000 --send-sysex-probe
   ```

## Recommended Merge Roadmap

Priority 1: Make connection work reliably.

- Keep current USB/MIDI distinction.
- Add clearer setup checklist in GUI.
- Add selectable input/output routing in GUI.
- Add live/dry-run toggle with explicit confirmation.
- Add read-only SysEx live send only when both input and output are selected and SysEx is explicitly enabled.

Priority 2: Import the web app's local sample workflow.

- Add local audio import.
- Add sample table.
- Keep waveform preview and WAV export integrated with the content-addressed
  device library.
- Add JSON manifest import/export.

Priority 3: Import project/timeline workflow.

- Add scene/track/clip models.
- Add timeline for local playback and MIDI events.
- Render pad assignments from imported manifests.

Priority 4: Add read-only hardware metadata workflow.

- Send identity.
- Send TE echo.
- Send file init.
- List root.
- Cache complete device tree on connection.
- Preview selected hardware sound/track files with explicit playback start/stop.
- Export cached tree.
- Compare local samples to cached tree.

Priority 5: Consider write operations only after backups and read-only probes are verified.

- Keep upload/delete/move/metadata writes blocked by default.
- Require explicit unlock, visible warning, backup existence, and hardware smoke tests.
