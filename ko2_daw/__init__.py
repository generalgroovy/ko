"""Safe MIDI/DAW control helpers for external sampler experiments."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
from types import ModuleType

from ko2_daw.config import DAWConfig, DeviceSafetyConfig
from ko2_daw.controller import DAWController
from ko2_daw.midi import DryRunMidiBackend, MidiMessage


class _HardwareExplorerPatchLoader(importlib.abc.Loader):
    """Loader wrapper that patches ko2_daw.gui after normal import."""

    def __init__(self, wrapped_loader: importlib.abc.Loader):
        self.wrapped_loader = wrapped_loader

    def create_module(self, spec):
        if hasattr(self.wrapped_loader, "create_module"):
            return self.wrapped_loader.create_module(spec)
        return None

    def exec_module(self, module: ModuleType) -> None:
        self.wrapped_loader.exec_module(module)
        from ko2_daw.hardware_explorer import apply_hardware_explorer_patch

        apply_hardware_explorer_patch(module)


class _HardwareExplorerPatchFinder(importlib.abc.MetaPathFinder):
    """Intercept only ko2_daw.gui and delegate all real loading to PathFinder."""

    target = "ko2_daw.gui"

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.target:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        if isinstance(spec.loader, _HardwareExplorerPatchLoader):
            return spec
        spec.loader = _HardwareExplorerPatchLoader(spec.loader)
        return spec


def _install_hardware_explorer_patch() -> None:
    if "ko2_daw.gui" in sys.modules:
        from ko2_daw.hardware_explorer import apply_hardware_explorer_patch

        apply_hardware_explorer_patch(sys.modules["ko2_daw.gui"])
        return
    if not any(isinstance(finder, _HardwareExplorerPatchFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _HardwareExplorerPatchFinder())


_install_hardware_explorer_patch()

__all__ = [
    "DAWConfig",
    "DAWController",
    "DeviceSafetyConfig",
    "DryRunMidiBackend",
    "MidiMessage",
]
