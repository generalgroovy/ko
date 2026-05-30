"""Song timeline GUI integration for songs 1-9 and tracks A-D."""

from __future__ import annotations

import threading
from typing import Any

from ko2_daw.midi import MidiMessage
from ko2_daw.song_timeline import DEFAULT_STEPS, SONG_NUMBERS, TRACKS, SongTimelineSet

POLL_MS = 120
NOTE_GROUPS = {
    "A": range(36, 48),
    "B": range(48, 60),
    "C": range(60, 72),
    "D": range(72, 84),
}
PROGRAM_GROUPS = {0: "A", 1: "B", 2: "C", 3: "D"}


class TPalette:
    bg = "#d8d4c8"
    panel = "#171915"
    grid = "#2a2d24"
    active = "#d7f58a"
    hit = "#f36f21"
    other = "#69724b"
    text = "#f3f1de"
    dark_text = "#11120f"


def apply_song_timeline_patch(gui_module: Any) -> None:
    """Patch timeline to show song slots, track lengths, and components."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_song_timeline_patch_installed", False):
        return

    tk = gui_module.tk
    original_init = app_class.__init__
    original_build_device_timeline = getattr(app_class, "_build_device_timeline")
    original_add_hardware_entry = app_class._add_hardware_entry
    original_clear_hardware_cache = app_class._clear_hardware_cache
    original_queue_midi_input = app_class._queue_midi_input
    original_device_group = getattr(app_class, "_device_group", None)
    original_mark_current_step = getattr(app_class, "_mark_current_step", None)

    def __init__(self, root):
        self.song_timeline = SongTimelineSet()
        self.song_timeline_pending: list[MidiMessage] = []
        self.song_timeline_lock = threading.Lock()
        original_init(self, root)
        self.root.after(POLL_MS, self._song_timeline_tick)

    def _build_device_timeline(self, parent) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(2, weight=1)

        selector = tk.Frame(parent, bg=TPalette.bg)
        selector.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        selector.columnconfigure(10, weight=1)
        tk.Label(selector, text="SONG", bg=TPalette.bg, fg=TPalette.dark_text).grid(
            row=0,
            column=0,
            padx=(0, 4),
        )
        self.song_buttons = {}
        for column, number in enumerate(SONG_NUMBERS, start=1):
            button = tk.Button(
                selector,
                text=str(number),
                command=lambda value=number: self._select_song_slot(value),
                width=3,
                bg="#efeadf",
                relief=tk.FLAT,
            )
            button.grid(row=0, column=column, padx=2)
            self.song_buttons[number] = button
        self.song_summary = tk.Label(
            selector,
            bg=TPalette.bg,
            fg=TPalette.dark_text,
            anchor="e",
            font=("Consolas", 10),
        )
        self.song_summary.grid(row=0, column=10, sticky="ew", padx=(8, 0))

        track_bar = tk.Frame(parent, bg=TPalette.bg)
        track_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.track_buttons = {}
        for column, track in enumerate(TRACKS):
            button = tk.Button(
                track_bar,
                text=f"TRACK {track}",
                command=lambda value=track: self._select_timeline_track(value),
                bg="#efeadf",
                relief=tk.FLAT,
                padx=10,
            )
            button.grid(row=0, column=column, sticky="ew", padx=2)
            track_bar.columnconfigure(column, weight=1)
            self.track_buttons[track] = button

        self.timeline_canvas = tk.Canvas(parent, height=190, bg="#050604", highlightthickness=0)
        self.timeline_canvas.grid(row=2, column=1, sticky="nsew")
        for index, lane in enumerate(TRACKS):
            label = tk.Label(
                parent,
                text=lane,
                bg=TPalette.bg,
                fg=TPalette.dark_text,
                font=("Consolas", 12, "bold"),
            )
            label.grid(row=2 + index, column=0, sticky="nw", padx=(0, 6))
        self.timeline_info = tk.Label(parent, bg=TPalette.bg, fg=TPalette.dark_text, anchor="w")
        self.timeline_info.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._draw_song_timeline()

    def _select_song_slot(self, number: int) -> None:
        self.song_timeline.select_song(number)
        self._set_action(f"song {number}")
        self._draw_song_timeline()
        if hasattr(self, "_record_protocol"):
            self._record_protocol("app", "song-select", f"song {number}", "timeline selection")

    def _select_timeline_track(self, track: str) -> None:
        self.song_timeline.select_track(track)
        self.group.set(track)
        self.session.selected_group = track
        self._set_action(f"track {track}")
        self._draw_song_timeline()

    def _device_group(self, group: str) -> None:
        if original_device_group is not None:
            original_device_group(self, group)
        self.song_timeline.select_track(group)
        self._draw_song_timeline()

    def _mark_current_step(self, lane: str) -> None:
        if original_mark_current_step is not None:
            original_mark_current_step(self, lane)
        step = int(self.runtime_state.clock_ticks % self.song_timeline.current_song.tracks[lane].length_steps)
        self.song_timeline.mark_step(lane, step, "pad", evidence="app action")
        self._draw_song_timeline()

    def _add_hardware_entry(self, kind: str, node: str, name: str, size: str, status: str) -> None:
        original_add_hardware_entry(self, kind, node, name, size, status)
        path = str(name or node or "")
        try:
            if hasattr(self, "hardware_tree"):
                selected = self.hardware_tree.selection()
                if selected:
                    path = selected[0]
        except Exception:
            pass
        self.song_timeline.infer_from_file_entry(path, kind, node, name, size)
        self._draw_song_timeline()

    def _clear_hardware_cache(self, silent: bool = False) -> None:
        original_clear_hardware_cache(self, silent=silent)
        self.song_timeline = SongTimelineSet()
        self._draw_song_timeline()

    def _queue_midi_input(self, message: MidiMessage) -> None:
        with self.song_timeline_lock:
            self.song_timeline_pending.append(message)
            self.song_timeline_pending[:] = self.song_timeline_pending[-512:]
        original_queue_midi_input(self, message)

    def _song_timeline_tick(self) -> None:
        with self.song_timeline_lock:
            pending = list(self.song_timeline_pending)
            self.song_timeline_pending.clear()
        for message in pending:
            self._song_timeline_observe(message)
        self._draw_song_timeline()
        self.root.after(POLL_MS, self._song_timeline_tick)

    def _song_timeline_observe(self, message: MidiMessage) -> None:
        if message.kind == "program_change" and message.program is not None:
            track = PROGRAM_GROUPS.get(int(message.program))
            if track:
                self.group.set(track)
                self.session.selected_group = track
                self.song_timeline.select_track(track)
                self._set_action(f"device selected track {track}")
            return
        if message.kind == "control_change" and message.control == 64 and message.value is not None:
            song = int(message.value) + 1
            if song in SONG_NUMBERS:
                self.song_timeline.select_song(song)
                self._set_action(f"device selected song {song}")
            return
        if message.kind == "note_on" and message.note is not None and message.velocity:
            track = _track_from_note(int(message.note))
            if not track:
                return
            self.group.set(track)
            self.session.selected_group = track
            step = int(self.runtime_state.clock_ticks % self.song_timeline.current_song.tracks[track].length_steps)
            component = f"note {message.note} vel {message.velocity}"
            self.song_timeline.mark_step(track, step, component, evidence="incoming MIDI")
            self.song_timeline.select_track(track)

    def _draw_song_timeline(self) -> None:
        canvas = getattr(self, "timeline_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        song_model = self.song_timeline.current_song
        selected_track = self.song_timeline.selected_track
        current_step = int(self.runtime_state.clock_ticks)
        width = max(canvas.winfo_width(), 760)
        lane_height = 34
        label_pad = 8
        for lane_index, track in enumerate(TRACKS):
            model = song_model.tracks[track]
            y0 = 8 + lane_index * lane_height
            y1 = y0 + 22
            steps = max(1, model.length_steps)
            step_gap = 2 if steps <= 64 else 1
            step_width = max(2, int((width - label_pad - step_gap * (steps + 1)) / steps))
            for step in range(steps):
                x0 = label_pad + step * (step_width + step_gap)
                x1 = x0 + step_width
                fill = TPalette.grid
                if step in model.hits:
                    fill = TPalette.hit if track == selected_track else TPalette.other
                if step == current_step % steps:
                    fill = TPalette.active
                canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
            canvas.create_text(
                width - 8,
                y0 + 11,
                anchor="e",
                fill=TPalette.text,
                font=("Consolas", 9),
                text=f"{steps} st | {model.component_label}",
            )
        self._refresh_song_timeline_buttons()
        if hasattr(self, "timeline_info"):
            track_model = song_model.tracks[selected_track]
            self.timeline_info.configure(
                text=(
                    f"Song {self.song_timeline.selected_song} | Track {selected_track} | "
                    f"length {track_model.length_steps} steps | "
                    f"components: {track_model.component_label} | evidence: {track_model.evidence}"
                )
            )

    def _refresh_song_timeline_buttons(self) -> None:
        for number, button in getattr(self, "song_buttons", {}).items():
            active = number == self.song_timeline.selected_song
            button.configure(bg=TPalette.active if active else "#efeadf")
        for track, button in getattr(self, "track_buttons", {}).items():
            active = track == self.song_timeline.selected_track
            button.configure(bg=TPalette.active if active else "#efeadf")
        if hasattr(self, "song_summary"):
            song = self.song_timeline.current_song
            filled = sum(bool(model.hits or model.components) for model in song.tracks.values())
            self.song_summary.configure(text=f"{filled}/4 tracks known | evidence {song.evidence}")

    app_class.__init__ = __init__
    app_class._build_device_timeline = _build_device_timeline
    app_class._select_song_slot = _select_song_slot
    app_class._select_timeline_track = _select_timeline_track
    app_class._device_group = _device_group
    app_class._mark_current_step = _mark_current_step
    app_class._add_hardware_entry = _add_hardware_entry
    app_class._clear_hardware_cache = _clear_hardware_cache
    app_class._queue_midi_input = _queue_midi_input
    app_class._song_timeline_tick = _song_timeline_tick
    app_class._song_timeline_observe = _song_timeline_observe
    app_class._draw_song_timeline = _draw_song_timeline
    app_class._refresh_song_timeline_buttons = _refresh_song_timeline_buttons
    app_class._song_timeline_patch_installed = True


def _track_from_note(note: int) -> str | None:
    for track, note_range in NOTE_GROUPS.items():
        if note in note_range:
            return track
    return None
