"""Final GUI stabilization and layout activation for the KO II GUI."""

from __future__ import annotations

from typing import Any


def apply_visual_stability_patch(gui_module: Any) -> None:
    """Stabilize rendering and activate the final device-surface layout."""

    from ko2_daw.gui_photo_layout import apply_photo_layout_patch

    apply_photo_layout_patch(gui_module)

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_visual_stability_patch_installed", False):
        return

    original_build_group_matrix = getattr(app_class, "_build_group_matrix", None)
    original_set_button_active = getattr(app_class, "_set_button_active", None)
    original_refresh_device_view = getattr(app_class, "_refresh_device_view", None)
    original_group_matrix_pad = getattr(app_class, "_group_matrix_pad", None)

    def _build_group_matrix(self, parent) -> None:
        if original_build_group_matrix is not None:
            original_build_group_matrix(self, parent)
        self._mark_matrix_widgets_owned()

    def _mark_matrix_widgets_owned(self) -> None:
        for button in getattr(self, "group_matrix_buttons", {}).values():
            setattr(button, "_ko2_matrix_managed", True)
        for button in getattr(self, "group_matrix_labels", {}).values():
            setattr(button, "_ko2_matrix_managed", True)

    def _set_button_active(self, button, active: bool) -> None:
        if getattr(button, "_ko2_matrix_managed", False):
            return
        if original_set_button_active is not None:
            original_set_button_active(self, button, active)

    def _refresh_device_view(self) -> None:
        if original_refresh_device_view is not None:
            original_refresh_device_view(self)
        if hasattr(self, "_refresh_group_matrix"):
            self._refresh_group_matrix()
        if hasattr(self, "_photo_refresh"):
            self._photo_refresh()

    def _group_matrix_pad(self, group: str, pad_index: int) -> None:
        if original_group_matrix_pad is None:
            return
        self._group_matrix_press(group, pad_index, "app", held=True)
        self.root.after(90, lambda: self._group_matrix_release(group, pad_index))
        original_group_matrix_pad(self, group, pad_index)

    app_class._build_group_matrix = _build_group_matrix
    app_class._mark_matrix_widgets_owned = _mark_matrix_widgets_owned
    app_class._set_button_active = _set_button_active
    app_class._refresh_device_view = _refresh_device_view
    app_class._group_matrix_pad = _group_matrix_pad
    app_class._visual_stability_patch_installed = True
