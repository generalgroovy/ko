# KO II project consolidation

The canonical repository is `generalgroovy/ko` (KO II Sampler DAW). Its July
implementation includes the desktop library, audio recording and rendering,
arrangement, read-only file discovery, download integrity checks, and project
archive verification. `generalgroovy/ko2` is the earlier May Web MIDI Lab.

| Browser lab concept | Canonical disposition |
| --- | --- |
| MIDI ports and identity | Existing desktop routing and diagnostics |
| TE framing, 7-bit packing, echo and file probes | Existing Python protocol implementation and tests |
| Guarded device operations | Existing desktop safety gates retained |
| Local sample metadata and JSON export | Existing sample library plus browser-library migration |
| Local preview and WAV export | Existing WAV preview, audio rendering and capture |
| Browser audio decoding | Export WAV in the browser first; no extra decoder dependency |
| Small waveform indicators | Not copied; the desktop audio workspace already provides audio workflows |

## Migration behavior

Use **Samples > IMPORT WEB LIBRARY** with the old JSON export and a folder of
WAVs downloaded with the browser lab's WAV buttons. The exporter names these
files from the sample name, replacing filename punctuation with underscores.
The importer uses the same rule; it does not follow paths from JSON metadata.
If two names produce the same WAV filename, rename the sample in the source
manifest and the corresponding WAV so that both names are unique.

Import uses actual WAV headers for duration, rate, channels, and bit depth.
Browser metadata is not treated as verified audio content. Existing local slots
are preserved and new samples occupy available slots in order. All entries are
checked before any are added, including directory containment and duplicates.
For a failed batch, correct the reported file or manifest entry and retry.

This is a local reference library: files are not copied or embedded. Keep the
selected WAV folder available for playback. The CLI creates a new desktop
manifest and refuses to overwrite an existing output; the GUI merges into the
current library, which can then be saved with **SAVE MANIFEST**.

Choose a destination when saving, then use **OPEN MANIFEST** to restore that
desktop library later. Opening validates every referenced WAV before replacing
the current library and asks before replacing a nonempty library. Desktop
manifests store references, not audio: back up the JSON and its WAV files
together. Relative WAV paths resolve from the desktop manifest's folder.

## Verification boundary

Migration is tested with generated PCM WAVs and browser-shaped manifests,
including atomic failure, malformed input, filename collisions, slot capacity,
and CLI execution without MIDI discovery. These checks do not establish device
transfer compatibility, physical audio playback, or human acceptance of the
desktop interface. Hardware observations in the main README are historical.

The old repository remains available for reference. No hardware writes, device
protocol changes, or archive deletion are required for consolidation.
