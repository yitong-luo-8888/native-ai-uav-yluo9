"""camera_pane_coordinator.py — camera-pane / home-slot lifecycle.

Owns up to _CAM_SLOT_COUNT CameraStreamPane widgets, each anchored to one
of a fixed number of "home slots" stacked top-to-bottom against the right
edge of the map viewport. Turning a drone's camera on claims a free slot
and spawns a pane; turning it off frees the slot and destroys the pane;
dragging a pane away from its home slot frees the slot for reuse without
touching the dragged pane, which keeps streaming wherever the user left it.

Not a QObject: CameraManager.mode_changed is connected straight to a plain
bound method (PyQt allows any callable as a slot), and this class doesn't
need to emit anything of its own for anyone else to observe.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PyQt5.QtWidgets import QWidget

from camera_config import CameraConfig
from camera_manager import CameraManager, CameraMode
from camera_video_panel import CameraStreamPane

_CAM_SLOT_COUNT = 3    # max simultaneous camera panes anchored to home slots
_CAM_SLOT_MARGIN = 10  # px, both the top margin and the gap between slots


class CameraPaneCoordinator:
    def __init__(
        self,
        camera_manager: CameraManager,
        cfg: CameraConfig,
        parent: QWidget,
        map_geometry: Callable[[], Tuple[int, int, int, int]],
    ) -> None:
        self._camera_manager = camera_manager
        self._cfg = cfg
        self._parent = parent
        self._map_geometry = map_geometry

        self._cam_panes: Dict[str, CameraStreamPane] = {}
        self._cam_slots: List[Optional[str]] = [None] * _CAM_SLOT_COUNT

        camera_manager.mode_changed.connect(self._on_cam_mode_changed)

    # -------------------- Public entry points --------------------

    def on_camera_click(self, name: str) -> None:
        """Routed from a drone card's [C] button, and reused as the [X]
        close callback on CameraStreamPane itself. Turning on is vetoed if
        no home slot is free — turning off always succeeds."""
        if self._camera_manager.get_mode(name) == CameraMode.STREAMING:
            self._camera_manager.set_mode(name, CameraMode.OFF)
        elif self._next_free_cam_slot() is not None:
            self._camera_manager.set_mode(name, CameraMode.STREAMING)
        # else: no launch points available — refuse silently, same as the
        # camera pane's own [X] close button routes back through here.

    def reposition_panes(self) -> None:
        """Call from the owner's resizeEvent to keep home-slotted panes
        anchored to the map viewport's top-right corner."""
        if not self._cam_panes:
            return
        mx, my, mw, mh = self._map_geometry()
        for slot, occupant in enumerate(self._cam_slots):
            if occupant is None:
                continue
            pane = self._cam_panes.get(occupant)
            if pane is not None:
                y = my + _CAM_SLOT_MARGIN + slot * (pane.height() + _CAM_SLOT_MARGIN)
                pane.reposition(mx + mw - pane.width() - _CAM_SLOT_MARGIN, y)

    # -------------------- Internal --------------------

    def _next_free_cam_slot(self) -> Optional[int]:
        for i, occupant in enumerate(self._cam_slots):
            if occupant is None:
                return i
        return None

    def _on_cam_mode_changed(self, name: str, mode: CameraMode) -> None:
        """Single source of truth for camera pane + home-slot lifecycle."""
        if mode == CameraMode.STREAMING:
            slot = self._next_free_cam_slot()
            if slot is None:
                # Capacity changed between the click veto-check and here
                # (shouldn't normally happen, single-threaded — stay safe).
                self._camera_manager.set_mode(name, CameraMode.OFF)
                return
            pane = CameraStreamPane(
                name, self._camera_manager, self._cfg,
                on_close=self.on_camera_click,
                on_dragged=self._on_cam_pane_dragged,
                parent=self._parent,
            )
            self._cam_panes[name] = pane
            self._cam_slots[slot] = name
            pane.show()
            pane.adjustSize()
            mx, my, mw, mh = self._map_geometry()
            y = my + _CAM_SLOT_MARGIN + slot * (pane.height() + _CAM_SLOT_MARGIN)
            pane.reposition(mx + mw - pane.width() - _CAM_SLOT_MARGIN, y)
        else:
            pane = self._cam_panes.pop(name, None)
            if pane is not None:
                pane.setParent(None)
                pane.deleteLater()
            for i, occupant in enumerate(self._cam_slots):
                if occupant == name:
                    self._cam_slots[i] = None

    def _on_cam_pane_dragged(self, name: str) -> None:
        """User dragged a pane away from its home slot — free the slot for
        reassignment; the dragged pane keeps streaming right where it is."""
        for i, occupant in enumerate(self._cam_slots):
            if occupant == name:
                self._cam_slots[i] = None
