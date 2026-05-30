"""All-groups performance matrix for simultaneous A-D playback visibility."""

from __future__ import annotations

import threading
from time import monotonic
from typing import Any

from ko2_daw.midi import MidiMessage

GROUPS = ("A", "B", "C", "D")
PAD_LABELS = (".", "0", "ENTER", "1", "2", "3", "4", "5", "6", "7", "8", "9")
NOTES_BY_GROUP = {
    "A": tuple(range(36, 48)),
    "B": tuple(range(48, 60)),
    "C": tuple(range(60, 72)),
    "D": tuple(range(72, 84)),
}
GROUP_BY_PROGRAM = {0: "A", 1: "B", 2: "C", 3: "D"}
POLL_MS = 50
RELEASE_FLASH_SEC = 0.18


class MatrixPalette:
    body = "#d8d4c8"
    panel = "#bdb7aa"
    dark = "#171915"
    pad = "#1f211d"
    pad_text = "#f5f0e4"
    group = "#f5f0e4"
    active = "#d7f58a"
    hit = "#f36f21"
    dim = "#69724b"


def apply_all_groups_matrix_patch(gui_module: Any) -> None:
    """Patch the device view with A-D group pad matrices visible simultaneously."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_all_groups_matrix_patch_installed", False):
        return

    tk = gui_module.tk
    original_init = app_class.__init__
    original_build_center = app_class._build_center_hardware_area
    original_queue_midi_input = app_class._queue_midi_input
    original_device_group = getattr(app_class, "_device_group", None)
    original_device_pad = getattr(app_class, "_device_pad", None)

    def __init__(self, root):
        self.group_matrix_buttons: dict[tuple[str, int], Any] = {}
        self.group_matrix_labels: dict[str, Any] = {}
        self.group_matrix_component_labels: dict[str, Any] = {}
        self.group_matrix_active_notes: dict[int, float | None] = {}
        self.group_matrix_pending: list[MidiMessage] = []
        self.group_matrix_lock = threading.Lock()
        original_init(self, root)
        self.root.after(POLL_MS, self._group_matrix_tick)

    def _build_center_hardware_area(self, parent) -> None:
        center = tk.Frame(parent, bg=MatrixPalette.panel, padx=10, pady=10)
        center.grid(row=0, column=1, sticky="nsew")
        center.columnconfigure(0, weight=1)
        center.rowconfigure(2, weight=1)

        self._build_matrix_mode_header(center)
        self._build_group_matrix(center)
        self._build_matrix_transport(center)
        self._refresh_group_matrix()

    def _build_matrix_mode_header(self, parent) -> None:
        header = tk.Frame(parent, bg=MatrixPalette.panel)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        modes = (
            "sound",
            "main",
            "tempo",
            "sample",
            "timing",
            "keys",
            "fx",
            "shift",
        )
        for column, key in enumerate(modes):
            header.columnconfigure(column, weight=1)
            label = key.upper()
            button = self._make_button(
                header,
                label,
                lambda value=key: self._device_mode_button(value),
                pale=key == "shift",
            )
            button.grid(row=0, column=column, sticky="ew", padx=3)
            self.device_buttons[key] = button
            if key not in self.device_controls:
                self._register_control(key, label, "mode")

    def _build_group_matrix(self, parent) -> None:
        matrix = tk.Frame(parent, bg=MatrixPalette.dark, padx=8, pady=8)
        matrix.grid(row=1, column=0, sticky="nsew")
        matrix.columnconfigure(2, weight=1)
        for row, group in enumerate(GROUPS):
            matrix.rowconfigure(row, weight=1)
            group_button = self._make_button(
                matrix,
                f"GROUP {group}",
                lambda value=group: self._device_group(value),
                pale=True,
            )
            group_button.grid(row=row, column=0, sticky="nsew", padx=(0, 6), pady=4)
            self.device_buttons[f"group_{group.lower()}"] = group_button
            self.group_matrix_labels[group] = group_button
            if f"group_{group.lower()}" not in self.device_controls:
                self._register_control(f"group_{group.lower()}", f"GROUP {group}", "group")

            pad_frame = tk.Frame(matrix, bg=MatrixPalette.dark)
            pad_frame.grid(row=row, column=1, sticky="nsew", pady=4)
            for index, label in enumerate(PAD_LABELS):
                pad_frame.columnconfigure(index, weight=1)
                button = tk.Button(
                    pad_frame,
                    text=label,
                    command=lambda grp=group, pad=index: self._group_matrix_pad(grp, pad),
                    bg=MatrixPalette.pad,
                    fg=MatrixPalette.pad_text,
                    activebackground=MatrixPalette.hit,
                    activeforeground="#11120f",
                    relief=tk.FLAT,
                    bd=0,
                    padx=5,
                    pady=7,
                    font=("Segoe UI", 9, "bold"),
                    width=5,
                )
                button.grid(row=0, column=index, sticky="nsew", padx=2)
                self.group_matrix_buttons[(group, index)] = button
                key = f"group_{group.lower()}_pad_{index}"
                self.device_buttons[key] = button
                if key not in self.device_controls:
                    self._register_control(key, f"{group}:{label}", "pad")

            component = tk.Label(
                matrix,
                bg=MatrixPalette.dark,
                fg=MatrixPalette.pad_text,
                font=("Consolas", 9),
                anchor="w",
                justify=tk.LEFT,
                width=32,
            )
            component.grid(row=row, column=2, sticky="nsew", padx=(8, 0), pady=4)
            self.group_matrix_component_labels[group] = component

    def _build_matrix_transport(self, parent) -> None:
        transport = tk.Frame(parent, bg=MatrixPalette.panel)
        transport.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        controls = (
            ("record", "REC", self._record),
            ("play", "PLAY", self._start),
            ("continue", "CONT", self._continue),
            ("stop", "STOP", self._stop),
            ("panic", "PANIC", self._panic),
        )
        for column, (key, label, command) in enumerate(controls):
            transport.columnconfigure(column, weight=1)
            button = self._make_button(
                transport,
                label,
                lambda name=key, action=command: self._device_transport(name, action),
                pale=key in {"stop", "panic"},
            )
            button.grid(row=0, column=column, sticky="ew", padx=3)
            self.device_buttons[key] = button
            if key not in self.device_controls:
                self._register_control(key, label, "transport")

        self.device_status = tk.Label(
            parent,
            bg=MatrixPalette.dark,
            fg=MatrixPalette.active,
            font=("Consolas", 11, "bold"),
            anchor="w",
            padx=8,
            pady=6,
        )
        self.device_status.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _queue_midi_input(self, message: MidiMessage) -> None:
        with self.group_matrix_lock:
            self.group_matrix_pending.append(message)
            self.group_matrix_pending[:] = self.group_matrix_pending[-512:]
        original_queue_midi_input(self, message)

    def _device_group(self, group: str) -> None:
        if original_device_group is not None:
            original_device_group(self, group)
        self._group_matrix_select_group(group, "app")

    def _device_pad(self, label: str) -> None:
        if original_device_pad is not None:
            original_device_pad(self, label)
        group = self.group.get()
        index = _label_to_pad_index(label)
        self._group_matrix_press(group, index, "app")

    def _group_matrix_pad(self, group: str, pad_index: int) -> None:
        self.group.set(group)
        self.session.selected_group = group
        if hasattr(self, "song_timeline"):
            self.song_timeline.select_track(group)
        note = NOTES_BY_GROUP[group][pad_index]
        self._send_midi(MidiMessage.note_on(note, self.velocity.get(), channel=self.config.midi_channel))
        self._send_midi(MidiMessage.note_off(note, channel=self.config.midi_channel))
        if hasattr(self, "_mark_current_step"):
            self._mark_current_step(group)
        self._group_matrix_press(group, pad_index, "app")
        self._set_action(f"{group}:{PAD_LABELS[pad_index]}")

    def _group_matrix_tick(self) -> None:
        with self.group_matrix_lock:
            pending = list(self.group_matrix_pending)
            self.group_matrix_pending.clear()
        for message in pending:
            self._group_matrix_observe(message)
        self._refresh_group_matrix()
        self.root.after(POLL_MS, self._group_matrix_tick)

    def _group_matrix_observe(self, message: MidiMessage) -> None:
        if message.kind == "program_change" and message.program is not None:
            group = GROUP_BY_PROGRAM.get(int(message.program))
            if group:
                self._group_matrix_select_group(group, "device")
            return
        if message.kind == "note_on" and message.note is not None:
            group, pad = _note_to_group_pad(int(message.note))
            if not group or pad is None:
                return
            if message.velocity:
                self._group_matrix_press(group, pad, "device", held=True)
                return
            self._group_matrix_release(group, pad)
            return
        if message.kind == "note_off" and message.note is not None:
            group, pad = _note_to_group_pad(int(message.note))
            if group and pad is not None:
                self._group_matrix_release(group, pad)

    def _group_matrix_select_group(self, group: str, source: str) -> None:
        self.group.set(group)
        self.session.selected_group = group
        if hasattr(self, "song_timeline"):
            self.song_timeline.select_track(group)
        if hasattr(self, "_mark_control"):
            self._mark_control(f"group_{group.lower()}", source)
        self._refresh_group_matrix()

    def _group_matrix_press(self, group: str, pad_index: int, source: str, *, held: bool = False) -> None:
        note = NOTES_BY_GROUP[group][pad_index]
        self.group_matrix_active_notes[note] = None if held else monotonic() + RELEASE_FLASH_SEC
        if hasattr(self, "_mark_control"):
            self._mark_control(f"group_{group.lower()}_pad_{pad_index}", source)
        if hasattr(self, "song_timeline"):
            step = self.runtime_state.clock_ticks % self.song_timeline.current_song.tracks[group].length_steps
            self.song_timeline.mark_step(group, step, f"{group}:{PAD_LABELS[pad_index]}", evidence=source)
        self._refresh_group_matrix()

    def _group_matrix_release(self, group: str, pad_index: int) -> None:
        note = NOTES_BY_GROUP[group][pad_index]
        self.group_matrix_active_notes[note] = monotonic() + RELEASE_FLASH_SEC

    def _refresh_group_matrix(self) -> None:
        now = monotonic()
        expired = [
            note
            for note, until in self.group_matrix_active_notes.items()
            if until is not None and until < now
        ]
        for note in expired:
            self.group_matrix_active_notes.pop(note, None)
        selected_group = self.group.get()
        for group in GROUPS:
            group_button = self.group_matrix_labels.get(group)
            if group_button is not None:
                active = group == selected_group
                group_button.configure(bg=MatrixPalette.active if active else MatrixPalette.group)
            for index, note in enumerate(NOTES_BY_GROUP[group]):
                button = self.group_matrix_buttons.get((group, index))
                if button is None:
                    continue
                if note in self.group_matrix_active_notes:
                    button.configure(bg=MatrixPalette.hit, fg="#11120f", relief="sunken")
                else:
                    button.configure(bg=MatrixPalette.pad, fg=MatrixPalette.pad_text, relief="flat")
            label = self.group_matrix_component_labels.get(group)
            if label is not None:
                label.configure(text=self._group_matrix_summary(group))

    def _group_matrix_summary(self, group: str) -> str:
        active = [
            PAD_LABELS[index]
            for index, note in enumerate(NOTES_BY_GROUP[group])
            if note in self.group_matrix_active_notes
        ]
        parts = [f"{group}  active: {', '.join(active) if active else '-'}"]
        if hasattr(self, "song_timeline"):
            song = self.song_timeline.current_song
            model = song.tracks[group]
            parts.append(f"len {model.length_steps} | {model.component_label}")
        elif hasattr(self, "runtime_state"):
            parts.append(f"notes {len(self.runtime_state.active_notes)}")
        return "\n".join(parts)

    app_class.__init__ = __init__
    app_class._build_center_hardware_area = _build_center_hardware_area
    app_class._build_matrix_mode_header = _build_matrix_mode_header
    app_class._build_group_matrix = _build_group_matrix
    app_class._build_matrix_transport = _build_matrix_transport
    app_class._queue_midi_input = _queue_midi_input
    app_class._device_group = _device_group
    app_class._device_pad = _device_pad
    app_class._group_matrix_pad = _group_matrix_pad
    app_class._group_matrix_tick = _group_matrix_tick
    app_class._group_matrix_observe = _group_matrix_observe
    app_class._group_matrix_select_group = _group_matrix_select_group
    app_class._group_matrix_press = _group_matrix_press
    app_class._group_matrix_release = _group_matrix_release
    app_class._refresh_group_matrix = _refresh_group_matrix
    app_class._group_matrix_summary = _group_matrix_summary
    app_class._all_groups_matrix_patch_installed = True


def _note_to_group_pad(note: int) -> tuple[str | None, int | None]:
    for group, notes in NOTES_BY_GROUP.items():
        if note in notes:
            return group, notes.index(note)
    return None, None


def _label_to_pad_index(label: str) -> int:
    return PAD_LABELS.index(str(label))
