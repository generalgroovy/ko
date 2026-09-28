"""A local-only waveform and trim-copy dialog; workers never touch Tk widgets."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import wave
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ko2_daw.sample_edit import trim_copy, waveform


class SampleEditor(tk.Toplevel):
    """Inspect audio, select a region with clicks or seconds, and export a new WAV."""

    def __init__(self, parent: tk.Misc, path: str, on_saved: Callable[[Path], None]):
        super().__init__(parent)
        self.title("Trim sample copy")
        self.geometry("680x340")
        self.minsize(420, 320)
        self.source = Path(path)
        self.on_saved = on_saved
        self.duration = 0.0
        self.peaks: list[tuple[float, float]] = []
        self.results: queue.Queue = queue.Queue()
        self.saving = False
        self.start = tk.StringVar(value="0")
        self.end = tk.StringVar(value="0")
        self.edge = tk.StringVar(value="start")
        self.status = tk.StringVar(value="Reading waveform…")
        self.protocol("WM_DELETE_WINDOW", self._close)
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.source.name, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.canvas = tk.Canvas(frame, height=130, background="#171c21", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=8)
        self.canvas.bind("<Configure>", lambda _event: self._draw())
        self.canvas.bind("<Button-1>", self._select)
        self.canvas.bind("<B1-Motion>", self._select)
        row = ttk.Frame(frame)
        row.pack(fill="x")
        for label, variable, edge in (
            ("Start (s)", self.start, "start"),
            ("End (s)", self.end, "end"),
        ):
            ttk.Radiobutton(row, text=label, variable=self.edge, value=edge).pack(side="left")
            entry = ttk.Entry(row, textvariable=variable, width=12)
            entry.pack(side="left", padx=(0, 8))
            variable.trace_add("write", lambda *_args: self._draw())
        ttk.Label(frame, textvariable=self.status, wraplength=620).pack(anchor="w", pady=8)
        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        self.save_button = ttk.Button(
            actions, text="Save trimmed copy…", command=self._save, state="disabled"
        )
        self.save_button.pack(side="left")
        ttk.Button(actions, text="Reset", command=self._reset).pack(side="left", padx=8)
        ttk.Button(actions, text="Info", command=self._info).pack(side="right")
        self._worker("waveform", lambda: waveform(self.source))
        self.poll_id = self.after(80, self._poll)

    def _worker(self, kind: str, operation: Callable) -> None:
        def run() -> None:
            try:
                self.results.put((kind, operation(), None))
            except (OSError, ValueError, EOFError, wave.Error) as exc:
                self.results.put((kind, None, exc))

        threading.Thread(target=run, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, value, error = self.results.get_nowait()
                if kind == "save":
                    self.saving = False
                    self.save_button.configure(state="normal")
                if error:
                    self.status.set(str(error))
                elif kind == "waveform":
                    self.duration, self.peaks = value
                    self._reset()
                    self.save_button.configure(state="normal")
                    self.status.set("Choose an edge, then click the waveform or enter seconds.")
                else:
                    self.status.set(f"Saved {value.name}")
                    self.on_saved(value)
        except queue.Empty:
            pass
        self.poll_id = self.after(80, self._poll)

    def _reset(self) -> None:
        self.start.set("0")
        self.end.set(str(self.duration))

    def _select(self, event: tk.Event) -> None:
        if not self.duration or self.saving:
            return
        value = min(
            self.duration, max(0.0, event.x / max(1, self.canvas.winfo_width()) * self.duration)
        )
        (self.start if self.edge.get() == "start" else self.end).set(f"{value:.6f}")

    def _draw(self) -> None:
        self.canvas.delete("all")
        if not self.peaks or not self.duration:
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        try:
            start, end = float(self.start.get()), float(self.end.get())
            if 0 <= start < end <= self.duration:
                self.canvas.create_rectangle(
                    start / self.duration * width,
                    0,
                    end / self.duration * width,
                    height,
                    fill="#284d55",
                    outline="",
                )
        except ValueError:
            pass
        for index, (low, high) in enumerate(self.peaks):
            x = index / len(self.peaks) * width
            self.canvas.create_line(
                x, (1 - high) * height / 2, x, (1 - low) * height / 2, fill="#a1e3d1"
            )

    def _save(self) -> None:
        try:
            start, end = float(self.start.get()), float(self.end.get())
            if not 0 <= start < end <= self.duration:
                raise ValueError("Choose a start before the end, within the sample duration.")
        except ValueError as exc:
            self.status.set(str(exc))
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Save a new WAV copy",
            defaultextension=".wav",
            initialfile=f"{self.source.stem}-trim.wav",
            filetypes=[("WAV audio", "*.wav")],
        )
        if not target:
            return
        self.saving = True
        self.save_button.configure(state="disabled")
        self.status.set("Saving copy…")
        self._worker("save", lambda: trim_copy(self.source, target, start, end))

    def _info(self) -> None:
        messagebox.showinfo(
            "Local sample editing",
            "The shaded region is exported as a new PCM WAV and added to your local library. The original is preserved. Existing files cannot be replaced.\n\nChoose Start or End, then click or drag on the waveform; numeric seconds provide a keyboard alternative. All channels and the original sample rate are retained. Nothing is sent to the sampler.",
            parent=self,
        )

    def _close(self) -> None:
        if self.saving:
            self.status.set("Finish saving before closing this editor.")
            return
        self.after_cancel(self.poll_id)
        self.destroy()
