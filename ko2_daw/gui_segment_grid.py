"""A-D x 99 segment grid GUI for EP-133 style group slots."""

from __future__ import annotations

import threading
from typing import Any

from ko2_daw.group_segments import GROUPS, SEGMENT_NUMBERS, SegmentBank, program_to_group
from ko2_daw.midi import MidiMessage

POLL_MS = 140


class SegmentPalette:
    bg = "#0f1110"
    panel = "#171915"
    unknown = "#2a2d24"
    empty = "#3d4036"
    occupied = "#f36f21"
    selected = "#d7f58a"
    text = "#f5f0e4"
    dark = "#11120f"


def apply_segment_grid_patch(gui_module: Any) -> None:
    """Add a compact A1-D99 occupancy grid and keep it synchronized."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_segment_grid_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    original_init = app_class.__init__
    original_build_workspace = app_class._build_workspace
    original_add_hardware_entry = app_class._add_hardware_entry
    original_clear_hardware_cache = app_class._clear_hardware_cache
    original_queue_midi_input = app_class._queue_midi_input
    original_device_group = getattr(app_class, "_device_group", None)
    original_group_matrix_pad = getattr(app_class, "_group_matrix_pad", None)

    def __init__(self, root):
        self.segment_bank = SegmentBank()
        self.segment_buttons: dict[tuple[str, int], Any] = {}
        self.segment_pending: list[MidiMessage] = []
        self.segment_lock = threading.Lock()
        original_init(self, root)
        self.root.after(POLL_MS, self._segment_grid_tick)

    def _build_workspace(self, parent) -> None:
        original_build_workspace(self, parent)
        self._install_segment_tab(parent)

    def _install_segment_tab(self, parent) -> None:
        notebooks = [child for child in parent.winfo_children() if child.winfo_class() == "TNotebook"]
        if not notebooks:
            return
        notebook = notebooks[-1]
        segment_tab = tk.Frame(notebook, bg=SegmentPalette.bg, padx=8, pady=8)
        notebook.add(segment_tab, text="Segments A-D×99")
        self._build_segment_grid(segment_tab)

    def _build_segment_grid(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        header = tk.Frame(parent, bg=SegmentPalette.bg)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(1, weight=1)
        tk.Button(header, text="SCAN DEVICE", command=lambda: self._scan_complete_device_tree(auto=False)).grid(
            row=0,
            column=0,
            padx=(0, 6),
        )
        self.segment_status = tk.Label(
            header,
            bg=SegmentPalette.panel,
            fg=SegmentPalette.text,
            anchor="w",
            font=("Consolas", 10),
            padx=8,
            pady=5,
        )
        self.segment_status.grid(row=0, column=1, sticky="ew")

        canvas = tk.Canvas(parent, bg=SegmentPalette.bg, highlightthickness=0)
        y_scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=y_scroll.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        y_scroll.grid(row=1, column=1, sticky="ns")
        frame = tk.Frame(canvas, bg=SegmentPalette.bg)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))

        for group_row, group in enumerate(GROUPS):
            label = tk.Label(
                frame,
                text=group,
                bg=SegmentPalette.bg,
                fg=SegmentPalette.selected,
                font=("Consolas", 13, "bold"),
                width=3,
            )
            label.grid(row=group_row, column=0, sticky="nsew", padx=(0, 4), pady=3)
            for number in SEGMENT_NUMBERS:
                column = number
                button = tk.Button(
                    frame,
                    text=str(number),
                    width=3,
                    padx=1,
                    pady=3,
                    relief=tk.FLAT,
                    font=("Segoe UI", 7, "bold"),
                    command=lambda grp=group, num=number: self._select_segment_slot(grp, num),
                )
                button.grid(row=group_row, column=column, padx=1, pady=3)
                self.segment_buttons[(group, number)] = button
        self._refresh_segment_grid()

    def _select_segment_slot(self, group: str, number: int) -> None:
        self.segment_bank.select(group, number)
        self.group.set(group)
        self.session.selected_group = group
        if hasattr(self, "song_timeline"):
            self.song_timeline.select_track(group)
        self._set_action(f"selected {group}{number}")
        if hasattr(self, "_record_protocol"):
            self._record_protocol("app", "segment-select", f"{group}{number}", "selected in segment grid")
        self._refresh_segment_grid()

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
        slot = self.segment_bank.ingest_file_entry(
            path=path,
            kind=kind,
            node=node,
            name=name,
            size=size,
            status=status,
        )
        if slot and hasattr(self, "_record_protocol"):
            self._record_protocol("app", "segment-scan", slot.segment_id, slot.status_text)
        self._refresh_segment_grid()

    def _clear_hardware_cache(self, silent: bool = False) -> None:
        original_clear_hardware_cache(self, silent=silent)
        self.segment_bank = SegmentBank()
        self._refresh_segment_grid()

    def _queue_midi_input(self, message: MidiMessage) -> None:
        with self.segment_lock:
            self.segment_pending.append(message)
            self.segment_pending[:] = self.segment_pending[-512:]
        original_queue_midi_input(self, message)

    def _device_group(self, group: str) -> None:
        if original_device_group is not None:
            original_device_group(self, group)
        self.segment_bank.select(group, self.segment_bank.selected_segment)
        self._refresh_segment_grid()

    def _group_matrix_pad(self, group: str, pad_index: int) -> None:
        if original_group_matrix_pad is not None:
            original_group_matrix_pad(self, group, pad_index)
        number = pad_index + 1
        self.segment_bank.select(group, number)
        step = int(self.runtime_state.clock_ticks % 64)
        self.segment_bank.selected_slot.mark_hit(step, f"{group}{number}", evidence="app pad")
        self._refresh_segment_grid()

    def _segment_grid_tick(self) -> None:
        with self.segment_lock:
            pending = list(self.segment_pending)
            self.segment_pending.clear()
        for message in pending:
            self._segment_grid_observe(message)
        self._refresh_segment_grid()
        self.root.after(POLL_MS, self._segment_grid_tick)

    def _segment_grid_observe(self, message: MidiMessage) -> None:
        if message.kind == "program_change" and message.program is not None:
            group = program_to_group(int(message.program))
            if group:
                self.segment_bank.select(group, self.segment_bank.selected_segment)
                self.group.set(group)
                self.session.selected_group = group
            return
        if message.kind == "control_change" and message.control == 65 and message.value is not None:
            number = int(message.value) + 1
            if number in SEGMENT_NUMBERS:
                self.segment_bank.select(self.segment_bank.selected_group, number)
            return
        if message.kind == "note_on" and message.note is not None and message.velocity:
            step = int(self.runtime_state.clock_ticks % 64)
            component = f"note {message.note} vel {message.velocity}"
            self.segment_bank.mark_midi_note(int(message.note), step, component, evidence="incoming MIDI")

    def _refresh_segment_grid(self) -> None:
        if not getattr(self, "segment_buttons", None):
            return
        selected = (self.segment_bank.selected_group, self.segment_bank.selected_segment)
        for group, number in list(self.segment_buttons):
            button = self.segment_buttons[(group, number)]
            slot = self.segment_bank.slots[group][number]
            if (group, number) == selected:
                bg = SegmentPalette.selected
                fg = SegmentPalette.dark
            elif slot.occupied is True:
                bg = SegmentPalette.occupied
                fg = SegmentPalette.dark
            elif slot.occupied is False:
                bg = SegmentPalette.empty
                fg = SegmentPalette.text
            else:
                bg = SegmentPalette.unknown
                fg = SegmentPalette.text
            button.configure(bg=bg, fg=fg)
        if hasattr(self, "segment_status"):
            slot = self.segment_bank.selected_slot
            known = sum(1 for item in self.segment_bank.iter_slots() if item.occupied is not None)
            occupied = sum(1 for item in self.segment_bank.iter_slots() if item.occupied is True)
            self.segment_status.configure(
                text=(
                    f"selected {slot.segment_id} | {slot.status_text} | evidence {slot.evidence} | "
                    f"known {known}/396 occupied {occupied} | poll {self.segment_bank.last_poll}"
                )
            )

    app_class.__init__ = __init__
    app_class._build_workspace = _build_workspace
    app_class._install_segment_tab = _install_segment_tab
    app_class._build_segment_grid = _build_segment_grid
    app_class._select_segment_slot = _select_segment_slot
    app_class._add_hardware_entry = _add_hardware_entry
    app_class._clear_hardware_cache = _clear_hardware_cache
    app_class._queue_midi_input = _queue_midi_input
    app_class._device_group = _device_group
    app_class._group_matrix_pad = _group_matrix_pad
    app_class._segment_grid_tick = _segment_grid_tick
    app_class._segment_grid_observe = _segment_grid_observe
    app_class._refresh_segment_grid = _refresh_segment_grid
    app_class._segment_grid_patch_installed = True
