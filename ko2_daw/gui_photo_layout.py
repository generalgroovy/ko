"""Photo-informed EP-133 / K.O. II main control surface.

This patch is intentionally final in the launcher stack. It replaces the older
abstract center matrix with a layout that matches the uploaded device photo:
left fader/volume/group column, central 4x4 group/keypad area, right paired
mode controls, display, knobs, and transport.
"""

from __future__ import annotations

from typing import Any, Callable

from ko2_daw.midi import MidiMessage

GROUPS = ("A", "B", "C", "D")
PAD_GRID = [
    ["A", "7", "8", "9"],
    ["B", "4", "5", "6"],
    ["C", "1", "2", "3"],
    ["D", ".", "0", "ENTER"],
]
PAD_INDEX_BY_LABEL = {
    ".": 0,
    "0": 1,
    "ENTER": 2,
    "1": 3,
    "2": 4,
    "3": 5,
    "4": 6,
    "5": 7,
    "6": 8,
    "7": 9,
    "8": 10,
    "9": 11,
}
NOTES_BY_GROUP = {
    "A": tuple(range(36, 48)),
    "B": tuple(range(48, 60)),
    "C": tuple(range(60, 72)),
    "D": tuple(range(72, 84)),
}
GROUP_PROGRAMS = {"A": 0, "B": 1, "C": 2, "D": 3}

MODE_BUTTONS = {
    "sound": 20,
    "edit": 21,
    "main": 22,
    "commit": 23,
    "tempo": 24,
    "loop": 25,
    "sample": 26,
    "chop": 27,
    "timing": 28,
    "correct": 29,
    "fx": 32,
    "output": 33,
    "erase": 34,
    "system": 35,
    "keys": 30,
}


class PhotoPalette:
    body = "#d9d5ca"
    panel = "#c3bdb0"
    display = "#0b0d0f"
    display_text = "#8ed1ff"
    black = "#151611"
    black_text = "#f4efe3"
    white = "#f7f2e7"
    orange = "#f36f21"
    red = "#f05443"
    active = "#d7f58a"
    dim = "#817b70"
    group = "#e9e5dc"


def apply_photo_layout_patch(gui_module: Any) -> None:
    """Install the photo-informed main layout."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_photo_layout_patch_installed", False):
        return

    tk = gui_module.tk
    original_send_midi = app_class._send_midi
    original_queue_midi_input = app_class._queue_midi_input

    def _build_main_controls(self, parent) -> None:
        self.photo_buttons = {}
        self.photo_group_buttons = {}
        self.photo_pad_buttons = {}
        self.photo_active_notes = {}
        self.photo_mode = getattr(self, "device_mode", "main")
        self.photo_last = "ready"

        shell = tk.Frame(parent, bg=PhotoPalette.body, padx=12, pady=12)
        shell.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=2)
        shell.columnconfigure(2, weight=2)
        shell.rowconfigure(0, weight=1)

        self._photo_build_left(shell)
        self._photo_build_keypad(shell)
        self._photo_build_right(shell)
        self._photo_refresh()
        self.root.after(75, self._photo_tick)

    def _photo_build_left(self, parent) -> None:
        left = tk.Frame(parent, bg=PhotoPalette.panel, padx=10, pady=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)

        shift = _button(tk, left, "SHIFT", lambda: self._photo_mode_button("shift"), pale=True)
        shift.grid(row=0, column=0, sticky="ew", pady=(0, 8), columnspan=2)
        self.photo_buttons["shift"] = shift

        tk.Label(left, text="FADER", bg=PhotoPalette.panel, fg=PhotoPalette.black).grid(
            row=1,
            column=0,
            sticky="ew",
        )
        fader = tk.Scale(
            left,
            from_=127,
            to=0,
            orient=tk.VERTICAL,
            length=210,
            bg=PhotoPalette.panel,
            troughcolor=PhotoPalette.black,
            highlightthickness=0,
            command=lambda value: self._photo_fader(value),
        )
        fader.set(96)
        fader.grid(row=2, column=0, rowspan=5, sticky="ns")

        vol = tk.Scale(
            left,
            label="VOLUME",
            from_=0,
            to=127,
            orient=tk.HORIZONTAL,
            bg=PhotoPalette.panel,
            highlightthickness=0,
            command=lambda value: self._photo_cc("volume", 7, value),
        )
        vol.set(96)
        vol.grid(row=1, column=1, sticky="ew", pady=(0, 8))

        for row, group in enumerate(GROUPS, start=2):
            button = _button(tk, left, group, lambda value=group: self._photo_group(value), pale=True)
            button.grid(row=row, column=1, sticky="nsew", pady=4)
            self.photo_group_buttons[group] = button
            self.photo_buttons[f"group_{group.lower()}"] = button

        utility = tk.Frame(left, bg=PhotoPalette.panel)
        utility.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for column, (label, command) in enumerate(
            (
                ("FILES", self._show_device_file_explorer),
                ("PROTOCOL", self._show_protocol_window),
            )
        ):
            utility.columnconfigure(column, weight=1)
            _button(tk, utility, label, command, pale=True, small=True).grid(
                row=0,
                column=column,
                sticky="ew",
                padx=3,
            )

    def _photo_build_keypad(self, parent) -> None:
        middle = tk.Frame(parent, bg=PhotoPalette.panel, padx=12, pady=12)
        middle.grid(row=0, column=1, sticky="nsew", padx=4)
        for column in range(4):
            middle.columnconfigure(column, weight=1, uniform="keys")
        for row in range(4):
            middle.rowconfigure(row, weight=1, uniform="keys")

        for row, labels in enumerate(PAD_GRID):
            for column, label in enumerate(labels):
                if label in GROUPS:
                    button = _button(
                        tk,
                        middle,
                        label,
                        lambda value=label: self._photo_group(value),
                        pale=True,
                    )
                    self.photo_group_buttons[label] = button
                    self.photo_buttons[f"group_{label.lower()}"] = button
                else:
                    index = PAD_INDEX_BY_LABEL[label]
                    button = _button(
                        tk,
                        middle,
                        label,
                        lambda value=label: self._photo_pad(value),
                        big=True,
                    )
                    self.photo_pad_buttons[index] = button
                    self.photo_buttons[f"pad_{label}"] = button
                button.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)

        transport = tk.Frame(middle, bg=PhotoPalette.panel)
        transport.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        controls: tuple[tuple[str, str, Callable[[], None], str], ...] = (
            ("record", "RECORD", self._record, PhotoPalette.orange),
            ("play", "PLAY", self._start, PhotoPalette.white),
            ("minus", "−", lambda: self._photo_cc("minus", 85, 127), PhotoPalette.white),
            ("plus", "+", lambda: self._photo_cc("plus", 86, 127), PhotoPalette.white),
        )
        for column, (key, label, command, color) in enumerate(controls):
            transport.columnconfigure(column, weight=1)
            button = _button(tk, transport, label, lambda k=key, cmd=command: self._photo_transport(k, cmd), bg=color)
            button.grid(row=0, column=column, sticky="ew", padx=4)
            self.photo_buttons[key] = button

    def _photo_build_right(self, parent) -> None:
        right = tk.Frame(parent, bg=PhotoPalette.panel, padx=10, pady=10)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)
        right.columnconfigure(2, weight=1)

        self.photo_display = tk.Label(
            right,
            bg=PhotoPalette.display,
            fg=PhotoPalette.display_text,
            font=("Consolas", 18, "bold"),
            text="--:--",
            padx=10,
            pady=14,
        )
        self.photo_display.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        pairs = (
            (("sound", "SOUND"), ("edit", "EDIT")),
            (("main", "MAIN"), ("commit", "COMMIT")),
            (("tempo", "TEMPO"), ("loop", "LOOP")),
            (("sample", "SAMPLE"), ("chop", "CHOP")),
            (("timing", "TIMING"), ("correct", "CORRECT")),
            (("fx", "FX"), ("output", "OUTPUT")),
            (("erase", "ERASE"), ("system", "SYSTEM")),
        )
        for row, pair in enumerate(pairs, start=1):
            for column, (key, label) in enumerate(pair):
                button = _button(
                    tk,
                    right,
                    label,
                    lambda value=key: self._photo_mode_button(value),
                    bg=PhotoPalette.orange if key in {"commit", "sample"} else None,
                    pale=key in {"edit", "loop", "chop", "correct", "output", "system"},
                    small=True,
                )
                button.grid(row=row, column=column, sticky="ew", padx=3, pady=3)
                self.photo_buttons[key] = button

        keys = _button(tk, right, "KEYS", lambda: self._photo_mode_button("keys"), small=True)
        keys.grid(row=1, column=2, sticky="nsew", padx=3, pady=3)
        self.photo_buttons["keys"] = keys

        gain = tk.Scale(
            right,
            label="GAIN / X",
            from_=0,
            to=127,
            orient=tk.HORIZONTAL,
            bg=PhotoPalette.panel,
            highlightthickness=0,
            command=lambda value: self._photo_cc("x", 16, value),
        )
        gain.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        swing = tk.Scale(
            right,
            label="SWING / Y",
            from_=0,
            to=127,
            orient=tk.HORIZONTAL,
            bg=PhotoPalette.panel,
            highlightthickness=0,
            command=lambda value: self._photo_cc("y", 17, value),
        )
        swing.grid(row=9, column=0, columnspan=2, sticky="ew")

        stop = _button(tk, right, "STOP", self._stop, pale=True, small=True)
        stop.grid(row=8, column=2, sticky="ew", padx=3, pady=(10, 3))
        connect = _button(tk, right, "CONNECT", self._connect_live, pale=True, small=True)
        connect.grid(row=9, column=2, sticky="ew", padx=3, pady=3)
        self.photo_buttons["stop"] = stop
        self.photo_buttons["connect"] = connect

    def _photo_mode_button(self, key: str) -> None:
        if key == "shift":
            self.device_shift = not getattr(self, "device_shift", False)
        else:
            self.device_mode = key
            self.photo_mode = key
        cc = MODE_BUTTONS.get(key)
        value = 0 if key == "shift" and not self.device_shift else 127
        if cc is not None:
            self._send_midi(MidiMessage.control_change(cc, value, channel=self.config.midi_channel))
        self._photo_mark(key, "app")
        self._set_action(f"device {key}")

    def _photo_group(self, group: str) -> None:
        self.group.set(group)
        self.session.selected_group = group
        if hasattr(self, "song_timeline"):
            self.song_timeline.select_track(group)
        if hasattr(self, "segment_bank"):
            self.segment_bank.select(group, self.segment_bank.selected_segment)
        self._send_midi(MidiMessage.program_change(GROUP_PROGRAMS[group], channel=self.config.midi_channel))
        self._photo_mark(f"group_{group.lower()}", "app")
        self._set_action(f"group {group}")

    def _photo_pad(self, label: str) -> None:
        group = self.group.get()
        index = PAD_INDEX_BY_LABEL[label]
        note = NOTES_BY_GROUP[group][index]
        velocity = int(self.velocity.get())
        self._send_midi(MidiMessage.note_on(note, velocity, channel=self.config.midi_channel))
        self._send_midi(MidiMessage.note_off(note, channel=self.config.midi_channel))
        if hasattr(self, "segment_bank"):
            self.segment_bank.select(group, min(index + 1, 99))
            step = int(self.runtime_state.clock_ticks % 64)
            self.segment_bank.selected_slot.mark_hit(step, f"{group}{index + 1}", evidence="app pad")
        self.photo_active_notes[note] = 2
        self._photo_mark(f"pad_{label}", "app")
        self._set_action(f"{group}:{label}")

    def _photo_transport(self, key: str, command: Callable[[], None]) -> None:
        command()
        self._photo_mark(key, "app")

    def _photo_cc(self, key: str, control: int, value) -> None:
        midi_value = int(float(value))
        self._send_midi(MidiMessage.control_change(control, midi_value, channel=self.config.midi_channel))
        self._photo_mark(key, "app")
        self._set_action(f"{key} {midi_value}")

    def _photo_fader(self, value) -> None:
        midi_value = int(float(value))
        self._send_mod_wheel(midi_value)
        self._photo_mark("fader", "app")

    def _send_midi(self, message: MidiMessage) -> bool:
        result = original_send_midi(self, message)
        if result:
            self._photo_observe(message, "app")
        return result

    def _queue_midi_input(self, message: MidiMessage) -> None:
        self._photo_observe(message, "device")
        original_queue_midi_input(self, message)

    def _photo_observe(self, message: MidiMessage, source: str) -> None:
        if message.kind == "program_change" and message.program is not None:
            group = {0: "A", 1: "B", 2: "C", 3: "D"}.get(int(message.program))
            if group:
                self.group.set(group)
                self.session.selected_group = group
                self._photo_mark(f"group_{group.lower()}", source)
            return
        if message.kind == "control_change" and message.control is not None:
            key = {value: name for name, value in MODE_BUTTONS.items()}.get(int(message.control))
            if key:
                self.device_mode = key
                self.photo_mode = key
                self._photo_mark(key, source)
            return
        if message.kind == "note_on" and message.note is not None:
            if message.velocity:
                self.photo_active_notes[int(message.note)] = None
                group, pad = _note_to_group_pad(int(message.note))
                if group is not None and pad is not None:
                    self.group.set(group)
                    self._photo_mark(f"pad_{PAD_GRID_LABEL_BY_INDEX[pad]}", source)
            else:
                self.photo_active_notes[int(message.note)] = 2
        elif message.kind == "note_off" and message.note is not None:
            self.photo_active_notes[int(message.note)] = 2

    def _photo_mark(self, key: str, source: str) -> None:
        self.photo_last = f"{key} [{source}]"
        if hasattr(self, "_state_poll_mark"):
            self._state_poll_mark(key, source)
        if hasattr(self, "_record_protocol"):
            self._record_protocol("app", "ui", self.photo_last, "photo layout")
        self._photo_refresh()

    def _photo_tick(self) -> None:
        expired = []
        for note, ttl in list(self.photo_active_notes.items()):
            if ttl is None:
                continue
            ttl -= 1
            if ttl <= 0:
                expired.append(note)
            else:
                self.photo_active_notes[note] = ttl
        for note in expired:
            self.photo_active_notes.pop(note, None)
        self._photo_refresh()
        self.root.after(75, self._photo_tick)

    def _photo_refresh(self) -> None:
        if not hasattr(self, "photo_buttons"):
            return
        selected_group = self.group.get()
        mode = getattr(self, "device_mode", getattr(self, "photo_mode", "main"))
        for group, button in self.photo_group_buttons.items():
            button.configure(bg=PhotoPalette.active if group == selected_group else PhotoPalette.group)
        for index, button in self.photo_pad_buttons.items():
            note = NOTES_BY_GROUP[selected_group][index]
            active = note in self.photo_active_notes
            button.configure(
                bg=PhotoPalette.orange if active else PhotoPalette.black,
                fg=PhotoPalette.black if active else PhotoPalette.black_text,
                relief="sunken" if active else "flat",
            )
        for key, button in self.photo_buttons.items():
            if key.startswith("group_") or key.startswith("pad_"):
                continue
            if key == mode:
                button.configure(bg=PhotoPalette.active, fg=PhotoPalette.black)
            elif key == "shift" and getattr(self, "device_shift", False):
                button.configure(bg=PhotoPalette.active, fg=PhotoPalette.black)
        if hasattr(self, "photo_display"):
            clock = int(getattr(self.runtime_state, "clock_ticks", 0))
            text = f"{selected_group}{getattr(getattr(self, 'segment_bank', None), 'selected_segment', 1):02d} {clock % 999:03d}"
            self.photo_display.configure(text=text)

    app_class._build_main_controls = _build_main_controls
    app_class._photo_build_left = _photo_build_left
    app_class._photo_build_keypad = _photo_build_keypad
    app_class._photo_build_right = _photo_build_right
    app_class._photo_mode_button = _photo_mode_button
    app_class._photo_group = _photo_group
    app_class._photo_pad = _photo_pad
    app_class._photo_transport = _photo_transport
    app_class._photo_cc = _photo_cc
    app_class._photo_fader = _photo_fader
    app_class._send_midi = _send_midi
    app_class._queue_midi_input = _queue_midi_input
    app_class._photo_observe = _photo_observe
    app_class._photo_mark = _photo_mark
    app_class._photo_tick = _photo_tick
    app_class._photo_refresh = _photo_refresh
    app_class._photo_layout_patch_installed = True


PAD_GRID_LABEL_BY_INDEX = {value: key for key, value in PAD_INDEX_BY_LABEL.items()}


def _button(
    tk,
    parent,
    label: str,
    command,
    *,
    bg: str | None = None,
    pale: bool = False,
    big: bool = False,
    small: bool = False,
):
    background = bg or (PhotoPalette.white if pale else PhotoPalette.black)
    foreground = PhotoPalette.black if background in {PhotoPalette.white, PhotoPalette.orange} else PhotoPalette.black_text
    return tk.Button(
        parent,
        text=label,
        command=command,
        bg=background,
        fg=foreground,
        activebackground=PhotoPalette.active,
        activeforeground=PhotoPalette.black,
        relief=tk.FLAT,
        bd=0,
        padx=8,
        pady=12 if big else 6 if small else 9,
        font=("Segoe UI", 16 if big else 8 if small else 10, "bold"),
    )


def _note_to_group_pad(note: int) -> tuple[str | None, int | None]:
    for group, notes in NOTES_BY_GROUP.items():
        if note in notes:
            return group, notes.index(note)
    return None, None
