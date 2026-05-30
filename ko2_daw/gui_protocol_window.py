"""Protocol transparency window for MIDI and SysEx traffic."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def apply_protocol_window_patch(gui_module: Any) -> None:
    """Patch KO2DawApp with a complete communication/protocol monitor."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_protocol_window_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    original_init = app_class.__init__
    original_build_menu = app_class._build_menu
    original_send_midi = app_class._send_midi
    original_queue_midi_input = app_class._queue_midi_input
    original_run_sysex_probe = app_class._run_sysex_probe

    def __init__(self, root):
        self.protocol_records: list[dict[str, str]] = []
        self.protocol_window = None
        self.protocol_tree = None
        self.protocol_detail = None
        original_init(self, root)

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="Protocol Monitor", command=self._show_protocol_window)
        tools.add_command(label="Clear Protocol Log", command=self._clear_protocol_log)
        menu.add_cascade(label="Protocol", menu=tools)

    def _show_protocol_window(self) -> None:
        if self.protocol_window and self.protocol_window.winfo_exists():
            self.protocol_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("KO II Protocol Monitor")
        win.geometry("980x520")
        win.configure(bg="#11120f")
        self.protocol_window = win
        toolbar = tk.Frame(win, bg="#11120f", padx=8, pady=6)
        toolbar.pack(fill=tk.X)
        tk.Button(toolbar, text="CLEAR", command=self._clear_protocol_log).pack(side=tk.LEFT)
        tk.Button(toolbar, text="COPY SELECTED", command=self._copy_selected_protocol).pack(
            side=tk.LEFT,
            padx=(6, 0),
        )
        tk.Label(
            toolbar,
            text="Every app/device MIDI and SysEx frame visible to this app is listed here.",
            bg="#11120f",
            fg="#d7f58a",
        ).pack(side=tk.RIGHT)

        columns = ("time", "direction", "kind", "summary")
        shell = tk.Frame(win, bg="#11120f")
        shell.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=3)
        shell.rowconfigure(1, weight=1)
        self.protocol_tree = ttk.Treeview(shell, columns=columns, show="headings", height=14)
        for column, width in (("time", 145), ("direction", 80), ("kind", 90), ("summary", 620)):
            self.protocol_tree.heading(column, text=column.title())
            self.protocol_tree.column(column, width=width, anchor="w")
        y_scroll = ttk.Scrollbar(shell, orient="vertical", command=self.protocol_tree.yview)
        self.protocol_tree.configure(yscrollcommand=y_scroll.set)
        self.protocol_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.protocol_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_protocol_detail())
        self.protocol_detail = tk.Text(shell, height=8, bg="#050604", fg="#f3f1de", wrap=tk.WORD)
        self.protocol_detail.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self._refresh_protocol_tree()

    def _record_protocol(self, direction: str, kind: str, summary: str, raw: str = "") -> None:
        record = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "direction": direction,
            "kind": kind,
            "summary": summary,
            "raw": raw,
        }
        self.protocol_records.append(record)
        self.protocol_records = self.protocol_records[-2000:]
        if self.protocol_tree and self.protocol_tree.winfo_exists():
            self._append_protocol_tree_record(record)

    def _append_protocol_tree_record(self, record: dict[str, str]) -> None:
        item_id = str(len(self.protocol_records) - 1)
        self.protocol_tree.insert(
            "",
            tk.END,
            iid=item_id,
            values=(record["time"], record["direction"], record["kind"], record["summary"]),
        )
        self.protocol_tree.see(item_id)

    def _refresh_protocol_tree(self) -> None:
        if not self.protocol_tree:
            return
        for item in self.protocol_tree.get_children():
            self.protocol_tree.delete(item)
        for index, record in enumerate(self.protocol_records):
            self.protocol_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(record["time"], record["direction"], record["kind"], record["summary"]),
            )

    def _show_protocol_detail(self) -> None:
        if not self.protocol_tree or not self.protocol_detail:
            return
        selected = self.protocol_tree.selection()
        self.protocol_detail.delete("1.0", tk.END)
        if not selected:
            return
        record = self.protocol_records[int(selected[0])]
        lines = [
            f"time: {record['time']}",
            f"direction: {record['direction']}",
            f"kind: {record['kind']}",
            f"summary: {record['summary']}",
            "",
            record.get("raw", ""),
        ]
        self.protocol_detail.insert(tk.END, "\n".join(lines))

    def _copy_selected_protocol(self) -> None:
        if not self.protocol_tree:
            return
        selected = self.protocol_tree.selection()
        if not selected:
            return
        record = self.protocol_records[int(selected[0])]
        text = "\n".join(
            [
                f"time: {record['time']}",
                f"direction: {record['direction']}",
                f"kind: {record['kind']}",
                f"summary: {record['summary']}",
                f"raw: {record.get('raw', '')}",
            ]
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _clear_protocol_log(self) -> None:
        self.protocol_records.clear()
        self._refresh_protocol_tree()
        if self.protocol_detail:
            self.protocol_detail.delete("1.0", tk.END)

    def _send_midi(self, message) -> bool:
        summary = message.display()
        raw = _message_raw(message)
        self._record_protocol("app -> device", message.kind, summary, raw)
        result = original_send_midi(self, message)
        if not result:
            self._record_protocol("app", "error", f"send failed: {summary}", raw)
        return result

    def _queue_midi_input(self, message) -> None:
        self._record_protocol("device -> app", message.kind, message.display(), _message_raw(message))
        original_queue_midi_input(self, message)

    def _run_sysex_probe(self, name: str, frame: bytes) -> None:
        self._record_protocol("app", "probe", name, frame.hex(" "))
        original_run_sysex_probe(self, name, frame)

    app_class.__init__ = __init__
    app_class._build_menu = _build_menu
    app_class._show_protocol_window = _show_protocol_window
    app_class._record_protocol = _record_protocol
    app_class._append_protocol_tree_record = _append_protocol_tree_record
    app_class._refresh_protocol_tree = _refresh_protocol_tree
    app_class._show_protocol_detail = _show_protocol_detail
    app_class._copy_selected_protocol = _copy_selected_protocol
    app_class._clear_protocol_log = _clear_protocol_log
    app_class._send_midi = _send_midi
    app_class._queue_midi_input = _queue_midi_input
    app_class._run_sysex_probe = _run_sysex_probe
    app_class._protocol_window_patch_installed = True


def _message_raw(message: Any) -> str:
    data = getattr(message, "data", None)
    if data:
        return bytes(data).hex(" ")
    return message.display() if hasattr(message, "display") else repr(message)
