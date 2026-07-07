# EP-133 File Protocol Knowledge

Verified against the connected EP-133 on June 11, 2026. All discovery in this
document used read-only operations. Device upload, delete, move, restore, and
metadata writes remain blocked.

## Transport

- MIDI transport: direct Windows WinMM input/output named `EP-133`.
- Manufacturer SysEx id: `00 20 76`.
- TE frame marker: `40`.
- File command: `05`.
- Payload bytes are packed into MIDI-safe 7-bit data.
- Requests and responses use a 14-bit request id.
- Responses must be matched by command and request id. The device can emit
  unrelated diagnostic SysEx while a request is pending.

## File Session

File init request payload:

```text
01 flags max_response_length:u32be
```

The connected unit returned a 512-byte file-protocol chunk size. The practical
GET data payload observed through the packed SysEx transport is 324 raw bytes
per full page.

## Directory Listing

List request payload:

```text
04 page:u16be parent_node:u16be
```

Each response starts with the returned page number followed by zero or more
records:

```text
node:u16be flags:u8 size:u32be utf8_name:nul
```

Confirmed roots:

- node 1000: `/sounds`
- node 2000: `/projects`

The June 11 snapshot contains 328 PCM sounds and nine project directories.

## File Download

GET init request:

```text
03 00 node:u16be offset:u32be
```

GET init response:

```text
node:u16be flags:u8 size:u32be utf8_name:nul padding...
```

GET data request:

```text
03 01 page:u16be
```

GET data response:

```text
page:u16be raw_file_bytes...
```

The client must continue requesting pages until exactly the declared byte
count has been received. Empty early pages, unexpected page numbers, overflow,
or a size mismatch are failures.

Verified sound download:

- node: 207
- device path: `/sounds/207.pcm`
- device metadata name: `closed hat foot`
- size: 3,988 bytes
- pages: 13
- page sizes: twelve 324-byte pages plus one 100-byte page
- SHA-256:
  `a6776d9fc2fded058e33c98874b7ce51eede2f6eea71b6edd9968f506899befd`
- CRC32: `2251392378` (`0x8631857a`)
- metadata CRC matched the downloaded bytes
- format: signed 16-bit PCM, mono, 46,875 Hz
- frames: 1,994

## Metadata

Metadata GET request:

```text
07 02 node:u16be page:u16be [utf8_key:nul]
```

Each response begins with the returned page and contains part of a UTF-8 JSON
object. A NUL terminator marks the last page.

Observed sound metadata fields include:

- `name`
- `channels`
- `samplerate`
- `format`
- `crc`
- `sound.playmode`
- `sound.rootnote`
- `sound.pitch`
- `sound.pan`
- `sound.amplitude`
- `sound.bars`
- `sound.bpm`
- `sound.loopstart`
- `sound.loopend`
- `envelope.attack`
- `envelope.release`
- `time.mode`

The metadata `crc` value is the standard CRC32 of the raw PCM bytes.

## Project Archives

All nine `/projects` nodes were downloaded through complete read-only GET
transactions and verified against their local manifests:

| Slot | Node | Bytes | Pages | SHA-256 | Assigned pads | Patterns | Files | `fx_settings` |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 01 | 3000 | 55808 | 173 | `6437a3ac94d1539a79d829c3c51d7a511aff34d3139d151cefb524c604440e34` | 19 | 0 | 50 | absent |
| 02 | 4000 | 138752 | 429 | `4251de8ae6e7c407329154b6e28e667a5cb0e1a06c4887e2c83c1cd3f64075f5` | 35 | 62 | 113 | 160 bytes |
| 03 | 5000 | 83968 | 260 | `87d0721ebc08d6bed115ae1824fbffef805b4074e10dd6ae0d3f079ec0281655` | 42 | 21 | 72 | 160 bytes |
| 04 | 6000 | 82432 | 255 | `00568b4873fef86a17ecafdb68f58d992eef4360418f75938e473d75e805e1ae` | 17 | 24 | 75 | 160 bytes |
| 05 | 7000 | 74240 | 230 | `7fa031d324b4c163fafceb32b7f344a70e65c492c741152f4f4dc30763b013ff` | 42 | 16 | 67 | 160 bytes |
| 06 | 8000 | 112640 | 348 | `8c91713ea5198be77711f15f4852435afe901cec87639bfbfcb6195b5e23b6dc` | 19 | 55 | 105 | absent |
| 07 | 9000 | 117248 | 362 | `fb5918957d8d63f85db7a6db814294f03c426a43c3ccbf7b6894caa4bd6748c1` | 36 | 56 | 107 | 160 bytes |
| 08 | 10000 | 125952 | 389 | `c5da9eaa0ebd8e12488f7bc2cfcff92102b94fe0225e5bb64f5165a595e2eaa5` | 23 | 56 | 107 | 160 bytes |
| 09 | 11000 | 65024 | 201 | `014e86728122495190d12d11c1733d70ac9139f63e4f7b31c7255eebc0f5b0f1` | 37 | 8 | 59 | 160 bytes |

Every archive has six directory entries and 48 fixed-size, 27-byte pad records
at `pads/{a-d}/p{01-12}`. Every capture also has a 712-byte `scenes` record and
a 222-byte `settings` record. Pattern members use
`patterns/{a-d}{01-99}`; only present records are included in an archive.

The pad sound id is a signed little-endian 16-bit integer at byte offset 1.
`0` is unassigned in the captured project. Project 01 currently has 19
assigned pads:

```text
A01-A06 -> 34
A07-A12 -> 1
B07     -> 7
D01-D02 -> 6
D03     -> 200
D04     -> 103
D05     -> 105
D07     -> 22
```

The parser accepts the actual lowercase, zero-padded names as well as the
reference tool's general pad path form. It does not label unknown fields in the
27-byte pad payload, `fx_settings`, patterns, `scenes`, or `settings` until their
meaning is verified by controlled before/after captures. Instead, it records
SHA-256, CRC32, byte count, nonzero byte count, and a bounded preview.

Two archives can be compared without extraction. The comparison reports
pad-to-sound changes and exact half-open changed byte ranges for each opaque
record. This supports controlled future reverse-engineering while preventing
unverified field names from entering the write path.

Across the current corpus, every pattern payload is a multiple of four bytes;
observed sizes range from 4 to 2,556 bytes. This is recorded as structural
evidence only. Neither the reference `codex/ko2-sysex-lab` branch at commit
`dd68354d6a5df4cb8640463652e1cf6ac8fc78de` nor the inspected EP Sample Tool
source provides a pattern, scene, settings, or FX field decoder. The EP Sample
Tool only reads and rewrites the pad sound id at offset 1.

The aggregate nine-slot catalog hash for this capture is:

```text
dd8093f1f9edd327ebc4a4be9cf33b7cbad83666dc0571b3b6f5a1f5399290f6
```

## Transaction Safety

A GET init creates a stateful device read transaction. A manual probe that
starts GET and does not consume every data page can leave the device file
service returning diagnostic SysEx such as:

```text
err lfs 6327 2_0_5
```

Recovery requires reconnecting or power-cycling the EP-133. Restarting the
Windows PnP device requires administrator access and is not used by the app.

The integrated downloader therefore:

- never exposes a standalone live GET-init command
- serializes all SysEx transactions
- reads every declared byte before metadata or local file work
- ignores unrelated diagnostic SysEx while matching responses
- suppresses progress callback failures until the device read completes
- blocks normal GUI disconnect, reconnect, and close while a download is active
- writes immutable content-addressed local bundles
- verifies SHA-256 for every download and CRC32 when metadata supplies it

## Local Bundle

Downloaded content is stored under:

```text
daw_projects/device_library/<node>_<name>/<sha256>/
```

Each bundle contains:

- the exact raw device bytes
- `metadata.json`
- `manifest.json`
- a WAV export when the PCM format is supported
- `project_analysis.json` for recognized project TAR archives

The slot directory also contains an atomic `latest.json` pointer. Existing
content is never replaced by different bytes under the same hash.

The project manager writes
`daw_projects/device_library/project_catalog.json`. Backup-missing skips only
bundles whose raw hash, manifest node, content-addressed directory, and safe TAR
parse all verify. Refresh-all downloads every slot again but still preserves
each distinct version under its SHA-256.

## References

- Teenage Engineering EP Sample Tool:
  https://teenage.engineering/apps/ep-sample-tool
- Offline EP Sample Tool source:
  https://github.com/garrettjwilke/ep_133_sample_tool
- KO II SysEx lab reference:
  https://github.com/generalgroovy/ko2/tree/codex/ko2-sysex-lab
