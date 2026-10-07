"""A local-only waveform and trim-copy dialog; workers never touch Tk widgets."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import wave
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ko2_daw.sample_edit import (
    selection_frames,
    slice_boundaries,
    slice_copies,
    trim_copy,
    waveform,
)


class SampleEditor(tk.Toplevel):
    """Inspect audio, select a region with clicks or seconds, and export a new WAV."""

    def __init__(self, parent: tk.Misc, path: str, on_saved: Callable[[list[Path]], None]):
        super().__init__(parent)
        self.title("Trim & slice copies")
        self.geometry("680x390")
        self.minsize(460, 390)
        self.source = Path(path)
        self.on_saved = on_saved
        self.duration = 0.0
        self.peaks: list[tuple[float, float]] = []
        self.results: queue.Queue = queue.Queue()
        self.saving = False
        self.reading = True
        self.cancel_event = threading.Event()
        self.rate = 0
        self.frames = 0
        self.start = tk.StringVar(value="0")
        self.end = tk.StringVar(value="0")
        self.edge = tk.StringVar(value="start")
        self.copies = tk.StringVar(value="One copy")
        self.selection = tk.StringVar(value="")
        self.status = tk.StringVar(value="Reading waveform…")
        self.saved_location = tk.StringVar(value="")
        self.range_controls = []
        self.protocol("WM_DELETE_WINDOW", self._close)
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        self.source_label = ttk.Label(
            frame, text=self.source.name, font=("Segoe UI", 11, "bold"), wraplength=620
        )
        self.source_label.pack(anchor="w")
        self.canvas = tk.Canvas(
            frame,
            height=130,
            background="#171c21",
            highlightthickness=2,
            highlightbackground="#171c21",
            highlightcolor="#1f8274",
            takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True, pady=8)
        self.canvas.bind("<Configure>", lambda _event: self._draw())
        self.canvas.bind("<Button-1>", self._select)
        self.canvas.bind("<B1-Motion>", self._select)
        for key in ("Left", "Right", "Home", "End"):
            self.canvas.bind(f"<{key}>", self._nudge)
        row = ttk.Frame(frame)
        row.pack(fill="x")
        for label, variable, edge in (
            ("Start (s)", self.start, "start"),
            ("End (s)", self.end, "end"),
        ):
            radio = ttk.Radiobutton(row, text=label, variable=self.edge, value=edge)
            radio.pack(side="left")
            entry = ttk.Entry(row, textvariable=variable, width=12)
            entry.pack(side="left", padx=(0, 8))
            self.range_controls.extend((radio, entry))
            variable.trace_add("write", lambda *_args: self._draw())
        ttk.Label(frame, textvariable=self.selection).pack(anchor="w", pady=(8, 0))
        export = ttk.Frame(frame)
        export.pack(fill="x", pady=(8, 0))
        ttk.Label(export, text="Make").pack(side="left", padx=(0, 8))
        self.count_box = ttk.Combobox(
            export,
            textvariable=self.copies,
            values=("One copy", "2 slices", "4 slices", "8 slices", "16 slices"),
            state="readonly",
            width=12,
        )
        self.count_box.pack(side="left")
        self.copies.trace_add("write", lambda *_args: self._draw())
        self.status_label = ttk.Label(frame, textvariable=self.status, wraplength=620)
        self.status_label.pack(anchor="w", pady=8)
        self.location_row = ttk.Frame(frame)
        ttk.Label(self.location_row, text="Last saved in").pack(side="left", padx=(0, 8))
        self.location_entry = ttk.Entry(
            self.location_row, textvariable=self.saved_location, state="readonly"
        )
        self.location_entry.pack(side="left", fill="x", expand=True)
        self.location_entry.bind(
            "<FocusIn>", lambda _event: self.location_entry.selection_range(0, "end")
        )
        frame.bind("<Configure>", self._resize_labels)
        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        self.save_button = ttk.Button(
            actions, text="Save trimmed copy…", command=self._save, state="disabled"
        )
        self.save_button.pack(side="left")
        self.reset_button = ttk.Button(actions, text="Select all", command=self._reset_or_retry)
        self.reset_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel)
        self.cancel_button.pack(side="left")
        ttk.Button(actions, text="Info", command=self._info).pack(side="right")
        self.edge.trace_add("write", lambda *_args: self._draw())
        self._sync_controls()
        self._worker("waveform", self._read)
        self.poll_id = self.after(80, self._poll)

    def _resize_labels(self, event) -> None:
        width = max(100, event.width - 28)
        self.source_label.configure(wraplength=width)
        self.status_label.configure(wraplength=width)

    def _sync_controls(self) -> None:
        busy = self.saving or self.reading
        for control in self.range_controls:
            control.configure(state="disabled" if busy or not self.frames else "normal")
        self.count_box.configure(state="disabled" if busy or not self.frames else "readonly")
        self.reset_button.configure(
            state="disabled" if busy else "normal",
            text="Select all" if self.frames else "Retry read",
        )
        self.cancel_button.configure(text="Cancel" if busy else "Close", state="normal")

    def _reset_or_retry(self) -> None:
        if self.saving or self.reading:
            return
        if self.frames:
            self._reset()
            return
        self.reading = True
        self.cancel_event.clear()
        self.status.set("Reading waveform…")
        self._sync_controls()
        self._worker("waveform", self._read)

    def _read(self):
        with wave.open(str(self.source), "rb") as source:
            rate, frames = source.getframerate(), source.getnframes()
        duration, peaks = waveform(self.source, cancel=self.cancel_event.is_set)
        return duration, peaks, rate, frames

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
                else:
                    self.reading = False
                if error:
                    self.status.set(
                        "Destination already exists. Choose another location or rename it first."
                        if isinstance(error, FileExistsError)
                        else str(error) or "The WAV is incomplete. Choose another source."
                    )
                elif kind == "waveform":
                    self.duration, self.peaks, self.rate, self.frames = value
                    self._reset()
                    self.status.set("Choose Start or End, then drag the waveform or enter seconds.")
                else:
                    self.status.set(
                        f"Saved {len(value)} WAV {'copy' if len(value) == 1 else 'slices'}. Original unchanged."
                    )
                    self.saved_location.set(str(value[0].parent.resolve()))
                    self.location_row.pack(fill="x", pady=(0, 8), before=self.save_button.master)
                    self.on_saved(value)
                self._sync_controls()
                self._draw()
        except queue.Empty:
            pass
        self.poll_id = self.after(80, self._poll)

    def _reset(self) -> None:
        if self.saving:
            return
        self.start.set("0")
        self.end.set(str(self.duration))

    def _count(self) -> int:
        return 1 if self.copies.get() == "One copy" else int(self.copies.get().split()[0])

    def _region(self) -> tuple[int, int]:
        return selection_frames(
            float(self.start.get()), float(self.end.get()), self.rate, self.frames
        )

    def _nudge(self, event: tk.Event) -> str:
        if not self.frames or self.saving:
            return "break"
        variable = self.start if self.edge.get() == "start" else self.end
        try:
            first, last = self._region()
        except ValueError:
            return "break"
        current = first if self.edge.get() == "start" else last
        step = max(1, round(self.rate / 100)) if event.state & 1 else 1
        if event.keysym == "Home":
            current = 0 if self.edge.get() == "start" else first + 1
        elif event.keysym == "End":
            current = last - 1 if self.edge.get() == "start" else self.frames
        else:
            current += step * (1 if event.keysym == "Right" else -1)
        current = (
            max(0, min(last - 1, current))
            if self.edge.get() == "start"
            else max(first + 1, min(self.frames, current))
        )
        variable.set(str(current / self.rate))
        return "break"

    def _select(self, event: tk.Event) -> None:
        if not self.duration or self.saving:
            return
        self.canvas.focus_set()
        frame = max(
            0, min(self.frames, round(event.x / max(1, self.canvas.winfo_width()) * self.frames))
        )
        try:
            first, last = self._region()
            frame = min(frame, last - 1) if self.edge.get() == "start" else max(frame, first + 1)
        except ValueError:
            # A click can also repair a malformed numeric edge.
            pass
        (self.start if self.edge.get() == "start" else self.end).set(str(frame / self.rate))

    def _draw(self) -> None:
        self.canvas.delete("all")
        if not self.peaks or not self.duration:
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        regions = []
        try:
            first, last = self._region()
            regions = slice_boundaries(first, last, self._count())
            for index, (start, end) in enumerate(regions):
                self.canvas.create_rectangle(
                    start / self.frames * width,
                    0,
                    end / self.frames * width,
                    height,
                    fill="#284d55" if index % 2 == 0 else "#365469",
                    outline="",
                )
            self.selection.set(
                f"Selected: {(last - first) / self.rate:.4f} s · {last - first:,} frames · {len(regions)} {'copy' if len(regions) == 1 else 'slices'}"
            )
            self.save_button.configure(state="disabled" if self.saving else "normal")
        except ValueError as exc:
            self.selection.set(
                str(exc)
                if str(exc).startswith(("Choose", "Each", "Start", "The"))
                else "Enter valid start and end seconds."
            )
            self.save_button.configure(state="disabled")
        self.save_button.configure(text="Save copy…" if self._count() == 1 else "Save slices…")
        self.count_box.configure(state="disabled" if self.saving else "readonly")
        self.reset_button.configure(state="disabled" if self.saving else "normal")
        for index, (low, high) in enumerate(self.peaks):
            x = index / len(self.peaks) * width
            self.canvas.create_line(
                x, (1 - high) * height / 2, x, (1 - low) * height / 2, fill="#a1e3d1"
            )
        if regions:
            first_x, last_x = first / self.frames * width, last / self.frames * width
            for left, right in ((0, first_x), (last_x, width)):
                self.canvas.create_rectangle(
                    left, 0, right, height, fill="#171c21", stipple="gray50", outline=""
                )
            for index, (start, end) in enumerate(regions):
                left, right = start / self.frames * width, end / self.frames * width
                if index:
                    self.canvas.create_line(
                        left,
                        0,
                        left,
                        height,
                        fill="#ffffff",
                        width=2,
                        dash=(4, 3),
                        tags="slice-boundary",
                    )
                if len(regions) > 1 and right - left >= 24:
                    center = (left + right) / 2
                    self.canvas.create_rectangle(
                        center - 10,
                        height - 22,
                        center + 10,
                        height - 4,
                        fill="#171c21",
                        outline="",
                    )
                    self.canvas.create_text(
                        center, height - 13, text=str(index + 1), fill="#ffffff", tags="slice-index"
                    )
            for edge, x in (("start", first_x), ("end", last_x)):
                self.canvas.create_line(
                    max(2, min(width - 2, x)),
                    0,
                    max(2, min(width - 2, x)),
                    height,
                    fill="#ffc857" if self.edge.get() == edge else "#ffffff",
                    width=3,
                    tags="selection-edge",
                )

    def _save(self) -> None:
        if self.saving or self.reading:
            return
        try:
            first, last = self._region()
            count = self._count()
            slice_boundaries(first, last, count)
            start, end = first / self.rate, last / self.rate
        except ValueError as exc:
            self.status.set(str(exc))
            return
        if count == 1:
            target = filedialog.asksaveasfilename(
                parent=self,
                title="Save a new WAV copy",
                defaultextension=".wav",
                initialfile=f"{self.source.stem}-trim.wav",
                filetypes=[("WAV audio", "*.wav")],
            )
        else:
            parent = filedialog.askdirectory(
                parent=self, title="Choose where to create the slice folder"
            )
            target = Path(parent) / f"{self.source.stem}-slices" if parent else None
        if not target:
            return
        self.saving = True
        self.cancel_event.clear()
        self._draw()
        self._sync_controls()
        self.status.set(f"Saving {count} WAV {'copy' if count == 1 else 'slices'}…")
        self._worker(
            "save",
            lambda: (
                [trim_copy(self.source, target, start, end, cancel=self.cancel_event.is_set)]
                if count == 1
                else slice_copies(
                    self.source, target, start, end, count, cancel=self.cancel_event.is_set
                )
            ),
        )

    def _cancel(self) -> None:
        if self.saving or self.reading:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status.set("Cancelling…")
        else:
            self._close()

    def _info(self) -> None:
        messagebox.showinfo(
            "Local sample editing",
            "The shaded region becomes new local PCM WAVs. Save the manifest afterward to keep the library. The original and existing destinations are preserved.\n\nChoose Start or End, then drag or enter seconds. Focus the waveform and use Left/Right for one frame, Shift for 10 ms, Home/End for the available boundary. Select all restores the entire sample.\n\nEqual slices divide the selected frames in order, with no overlap, resampling, fades or zero-crossing shifts. Their lengths differ by at most one frame; boundaries can click. Save slices creates a new <sample>-slices folder inside the folder you choose. If it already exists, rename it or choose another destination.\n\nCancel removes this operation's partial output. Closing during export waits for it to finish or cancel. Nothing is sent to the sampler. After saving, focus Last saved in to copy the full folder path.",
            parent=self,
        )

    def _close(self) -> None:
        if self.saving:
            self.status.set("Finish saving or press Cancel before closing.")
            return
        self.cancel_event.set()
        self.after_cancel(self.poll_id)
        self.destroy()

    def destroy(self) -> None:
        # The main window may destroy this child directly after its write guard.
        self.cancel_event.set()
        super().destroy()
