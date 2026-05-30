"""Continuous state polling and display for the KO II GUI."""

from __future__ import annotations

import threading
from time import monotonic
from typing import Any

from ko2_daw.midi import MidiMessage

POLL_MS = 60
PRESS_FLASH_SEC = 0.35

MODE_CC = {
    20: "sound",
    21: "edit",
    22: "main",
    23: "commit",
    24: "tempo",
    25: "loop",
    26: "sample",
    27: "chop",
    28: "timing",
    29: "correct",
    30: "keys",
    31: "shift",
    32: "fx",
    33: "output",
    34: "erase",
    35: "system",
}

GROUP_BY_PROGRAM = {0: "A", 1: "B", 2: "C", 3: "D"}


def apply_state_poll_patch(gui_module: Any) -> None:
    """Install a Tk-thread state poller and live state display."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_state_poll_patch_installed", False):
        return

    tk = gui_module.tk
    original_init = app_class.__init__
    original_build_top_panel = app_class._build_top_panel
    original_queue_midi_input = app_class._queue_midi_input
    original_mark_control = getattr(app_class, "_mark_control", None)
    original_set_action = app_class._set_action
    original_set_bpm = app_class._set_bpm
    original_send_mod_wheel = app_class._send_mod_wheel

    def __init__(self, root):
        self.state_poll_lock = threading.Lock()
        self.state_poll_pending: list[MidiMessage] = []
        self.state_poll_controls: dict[str, str] = {}
        self.state_poll_pressed_until: dict[str, float] = {}
        self.state_poll_values = {
            "mode": "main",
            "group": "A",
            "transport": "unknown",
            "shift": "off",
            "volume": "?",
            "fader": "?",
            "x": "?",
            "y": "?",
            "bpm": "?",
            "last": "none",
            "source": "none",
            "clock": "0",
            "notes": "0",
        }
        original_init(self, root)
        self._state_poll_start()

    def _build_top_panel(self, parent) -> None:
        original_build_top_panel(self, parent)
        display = _find_top_display(parent)
        if display is None:
            return
        poll = tk.Frame(display, bg="#171915", pady=5)
        poll.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        poll.columnconfigure(0, weight=1)
        poll.columnconfigure(1, weight=1)

        self.state_poll_primary = tk.Label(
            poll,
            fg="#d7f58a",
            bg="#171915",
            font=("Consolas", 11, "bold"),
            anchor="w",
            justify=tk.LEFT,
        )
        self.state_poll_primary.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.state_poll_levels = tk.Label(
            poll,
            fg="#f3f1de",
            bg="#171915",
            font=("Consolas", 10),
            anchor="w",
            justify=tk.LEFT,
        )
        self.state_poll_levels.grid(row=1, column=0, sticky="ew", pady=(3, 0))

        self.state_poll_buttons = tk.Label(
            poll,
            fg="#f2c230",
            bg="#171915",
            font=("Consolas", 10),
            anchor="w",
            justify=tk.LEFT,
        )
        self.state_poll_buttons.grid(row=1, column=1, sticky="ew", pady=(3, 0))
        self._tip(
            poll,
            "Live state poller: app state plus observable incoming MIDI. Hardware-only state is shown only when the device emits MIDI for it.",
        )

    def _queue_midi_input(self, message: MidiMessage) -> None:
        with self.state_poll_lock:
            self.state_poll_pending.append(message)
            self.state_poll_pending[:] = self.state_poll_pending[-512:]
        original_queue_midi_input(self, message)

    def _mark_control(self, key: str, source: str, state: str = "active") -> None:
        self._state_poll_mark(key, source, state)
        if original_mark_control is not None:
            original_mark_control(self, key, source, state)

    def _set_action(self, text: str) -> None:
        self._state_poll_mark(str(text), "app", "action")
        original_set_action(self, text)

    def _set_bpm(self, value: float) -> None:
        bpm = float(value)
        self.state_poll_values["bpm"] = str(int(round(bpm)))
        self._state_poll_mark("bpm", "app", self.state_poll_values["bpm"])
        original_set_bpm(self, bpm)

    def _send_mod_wheel(self, value: int) -> None:
        fader = int(float(value))
        self.state_poll_values["fader"] = str(fader)
        self._state_poll_mark("fader", "app", str(fader))
        original_send_mod_wheel(self, fader)

    def _state_poll_start(self) -> None:
        self.state_poll_values["bpm"] = str(int(round(float(self.bpm.get()))))
        self.state_poll_values["group"] = self.group.get()
        self._state_poll_tick()

    def _state_poll_tick(self) -> None:
        self._state_poll_consume_pending()
        self._state_poll_sample_runtime()
        self._state_poll_render()
        self.root.after(POLL_MS, self._state_poll_tick)

    def _state_poll_consume_pending(self) -> None:
        with self.state_poll_lock:
            pending = list(self.state_poll_pending)
            self.state_poll_pending.clear()
        for message in pending:
            self._state_poll_observe_message(message, "device")

    def _state_poll_sample_runtime(self) -> None:
        runtime = self.runtime_state
        self.state_poll_values["group"] = self.group.get()
        self.state_poll_values["transport"] = str(runtime.transport)
        self.state_poll_values["clock"] = str(runtime.clock_ticks)
        self.state_poll_values["notes"] = str(len(runtime.active_notes))
        if runtime.mod_wheel is not None:
            self.state_poll_values["fader"] = str(runtime.mod_wheel)
        controllers = getattr(runtime, "controllers", {})
        for control, target in (("7", "volume"), ("16", "x"), ("17", "y"), ("1", "fader")):
            if control in controllers:
                self.state_poll_values[target] = str(controllers[control])
        if getattr(runtime, "last_program", None) in GROUP_BY_PROGRAM:
            self.state_poll_values["group"] = GROUP_BY_PROGRAM[runtime.last_program]

    def _state_poll_observe_message(self, message: MidiMessage, source: str) -> None:
        if message.kind in {"start", "continue", "stop"}:
            self.state_poll_values["transport"] = message.kind
            self._state_poll_mark(message.kind, source)
            return
        if message.kind == "note_on" and message.note is not None and message.velocity:
            group, pad = _group_pad_from_note(gui_module, message.note)
            if group:
                self.state_poll_values["group"] = group
            self._state_poll_mark(f"pad {pad or message.note}", source, str(message.velocity))
            return
        if message.kind == "program_change" and message.program is not None:
            group = GROUP_BY_PROGRAM.get(int(message.program))
            if group:
                self.state_poll_values["group"] = group
                self._state_poll_mark(f"group {group}", source)
            return
        if message.kind == "control_change" and message.control is not None:
            self._state_poll_observe_cc(int(message.control), int(message.value or 0), source)
            return
        if message.kind == "clock":
            self.state_poll_values["clock"] = str(self.runtime_state.clock_ticks)

    def _state_poll_observe_cc(self, control: int, value: int, source: str) -> None:
        if control in MODE_CC:
            mode = MODE_CC[control]
            if mode == "shift":
                self.state_poll_values["shift"] = "on" if value else "off"
            else:
                self.state_poll_values["mode"] = mode
            self._state_poll_mark(mode, source, str(value))
            return
        targets = {1: "fader", 7: "volume", 16: "x", 17: "y"}
        if control in targets:
            target = targets[control]
            self.state_poll_values[target] = str(value)
            self._state_poll_mark(target, source, str(value))

    def _state_poll_mark(self, key: str, source: str, state: str = "active") -> None:
        now = monotonic()
        label = str(key).strip() or "unknown"
        self.state_poll_controls[label] = f"{state} / {source}"
        self.state_poll_pressed_until[label] = now + PRESS_FLASH_SEC
        self.state_poll_values["last"] = label
        self.state_poll_values["source"] = source
        if label in MODE_CC.values() and label != "shift":
            self.state_poll_values["mode"] = label
        if label == "shift":
            self.state_poll_values["shift"] = "on" if state not in {"0", "off"} else "off"

    def _state_poll_render(self) -> None:
        now = monotonic()
        active = [
            label
            for label, until in self.state_poll_pressed_until.items()
            if until >= now
        ]
        expired = [label for label, until in self.state_poll_pressed_until.items() if until < now]
        for label in expired:
            self.state_poll_pressed_until.pop(label, None)
        values = self.state_poll_values
        primary = (
            f"MODE {values['mode'].upper()}  GROUP {values['group']}  "
            f"TRANSPORT {values['transport'].upper()}  SHIFT {values['shift'].upper()}  "
            f"LAST {values['last']} [{values['source']}]"
        )
        levels = (
            f"BPM {values['bpm']} | VOL {values['volume']} | FADER {values['fader']} | "
            f"X {values['x']} | Y {values['y']} | CLOCK {values['clock']} | NOTES {values['notes']}"
        )
        buttons = "PRESS " + (", ".join(active[-8:]) if active else "none")
        if hasattr(self, "state_poll_primary"):
            self.state_poll_primary.configure(text=primary)
            self.state_poll_levels.configure(text=levels)
            self.state_poll_buttons.configure(text=buttons)

    app_class.__init__ = __init__
    app_class._build_top_panel = _build_top_panel
    app_class._queue_midi_input = _queue_midi_input
    app_class._mark_control = _mark_control
    app_class._set_action = _set_action
    app_class._set_bpm = _set_bpm
    app_class._send_mod_wheel = _send_mod_wheel
    app_class._state_poll_start = _state_poll_start
    app_class._state_poll_tick = _state_poll_tick
    app_class._state_poll_consume_pending = _state_poll_consume_pending
    app_class._state_poll_sample_runtime = _state_poll_sample_runtime
    app_class._state_poll_observe_message = _state_poll_observe_message
    app_class._state_poll_observe_cc = _state_poll_observe_cc
    app_class._state_poll_mark = _state_poll_mark
    app_class._state_poll_render = _state_poll_render
    app_class._state_poll_patch_installed = True


def _find_top_display(parent) -> Any | None:
    widgets = parent.grid_slaves(row=0, column=0)
    return widgets[0] if widgets else None


def _group_pad_from_note(gui_module: Any, note: int) -> tuple[str | None, str | None]:
    for group, notes in gui_module.PAD_NOTES.items():
        if note in notes:
            index = notes.index(note)
            return group, gui_module.PAD_LABELS[index]
    return None, None
