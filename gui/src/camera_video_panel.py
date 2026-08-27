"""camera_video_panel.py — child overlay(s) that display drone proxy-camera feeds.

Deliberately decoupled from DronePanel: driven only by CameraManager's
signals, never by anything DronePanel-specific, since the panel's own design
may change independently (see project notes).

Implemented as plain QWidget children of MapOverlay, absolutely positioned —
NOT top-level windows. A floating Qt.Dialog window (even without
WindowStaysOnTopHint) was found to interfere with mouse-event routing to
other widgets under X11/WSLg while it was open: dragging a drone onto the
mission path broke, and clicks on other controls (a second drone's camera
button, "Stop Simulation") stopped registering. Every other pane in this
app (DronePanel, ScenePane, ToolRibbon) already avoids this by
being a plain absolutely-positioned child sharing the parent's X11 window
rather than a separate top-level one — this follows the same pattern.

Up to three panes can be open at once, each anchored to one of three fixed
"home slots" stacked top-to-bottom (see MapOverlay._on_camera_click /
_on_cam_mode_changed for slot assignment). A pane keeps streaming even if
dragged away from its home slot; dragging just frees that slot for reuse.
"""

from __future__ import annotations

import math
from typing import Callable, Optional, Tuple

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from camera_config import CameraConfig
from camera_manager import CameraManager


def _drone_color(name: str) -> QColor:
    """Drone names double as their color (e.g. "Red" -> red) — mirrors
    drone_panel._drone_color, duplicated here rather than imported to keep
    this file decoupled from DronePanel."""
    c = QColor(name.lower())
    return c if c.isValid() else QColor(140, 140, 140)

_DARK_BG  = "rgba(30, 30, 30, 220)"
_TEXT_COL = "#e8e8e8"
_DIM_COL  = "#999999"

_NO_FRAME_TEXT = "no altitude\nreference yet"

_BTN_STYLE = (
    "QPushButton {"
    "  background: rgba(75,80,105,230); color: #dde;"
    "  border: 1px solid rgba(120,125,160,140);"
    "  border-radius: 4px; padding: 2px 10px; font-size: 11px;"
    "}"
    "QPushButton:hover    { background: rgba(100,105,140,255); color: #fff; }"
    "QPushButton:disabled { background: rgba(40,42,55,160); color: #55556a;"
    "  border-color: rgba(70,72,90,80); }"
)

_CLOSE_BTN_STYLE = (
    "QPushButton {"
    "  background: transparent; color: #e05050;"
    "  border: 1px solid #e05050; border-radius: 3px;"
    "  font-size: 11px; font-weight: bold; padding: 0px;"
    "}"
    "QPushButton:hover { background: #e05050; color: #111111; }"
)


def _fov_display_size(fov_h_deg: float, fov_v_deg: float, image_px: int) -> Tuple[int, int]:
    """Display size from the FOV's true footprint ratio, so the composited
    image exactly fills the window with no letterboxing. Tune fov_h_deg /
    fov_v_deg in camera.config to change the window's shape directly."""
    aspect = math.tan(math.radians(fov_h_deg / 2.0)) / math.tan(math.radians(fov_v_deg / 2.0))
    if aspect >= 1.0:
        return image_px, max(1, round(image_px / aspect))
    return max(1, round(image_px * aspect)), image_px


class _DragHandle(QLabel):
    """Title label that doubles as a drag grip — there's no native titlebar
    since this is a plain child widget, not a top-level window."""

    def __init__(self, text: str, pane: "CameraStreamPane") -> None:
        super().__init__(text)
        self._pane = pane
        self._drag_offset: Optional[QPoint] = None
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag_offset = ev.pos()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_offset is not None and (ev.buttons() & Qt.LeftButton):
            delta = ev.pos() - self._drag_offset
            if (not self._pane._user_positioned
                    and delta.manhattanLength() < QApplication.startDragDistance()):
                return
            self._pane.move(self._pane.pos() + delta)
            self._pane._mark_user_positioned()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(ev)


def _apply_frame(label: QLabel, pixmap: Optional[QPixmap]) -> None:
    if pixmap is None or pixmap.isNull():
        label.setPixmap(QPixmap())
        label.setText(_NO_FRAME_TEXT)
        return
    scaled = pixmap.scaled(
        label.width(), label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    label.setText("")
    label.setPixmap(scaled)


class CameraStreamPane(QWidget):
    """Child overlay for one streaming drone. Up to three can exist at once,
    each occupying a "home slot" assigned by MapOverlay.

    Only ever asks CameraManager to change mode, and only ever reports its
    own drag/close gestures via callbacks; MapOverlay owns pane and slot
    lifecycle from one place, matching how every other pane in this app is
    managed.
    """

    def __init__(self, name: str, camera_manager: CameraManager, cfg: CameraConfig,
                 on_close: Callable[[str], None],
                 on_dragged: Callable[[str], None],
                 parent: QWidget) -> None:
        super().__init__(parent)
        self.drone_name = name
        self._mgr = camera_manager
        self._on_close = on_close
        self._on_dragged = on_dragged
        self._user_positioned = False  # once dragged, resize no longer re-snaps it

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {_DARK_BG}; border-radius: 4px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        name_hex = _drone_color(name).name()
        title_lbl = _DragHandle(f'Camera — <span style="color:{name_hex};">{name}</span>', self)
        title_lbl.setStyleSheet(f"color: {_TEXT_COL}; font-weight: bold; background: transparent;")
        title_row.addWidget(title_lbl, 1)
        close_btn = QPushButton("X")
        close_btn.setFixedSize(18, 18)
        close_btn.setStyleSheet(_CLOSE_BTN_STYLE)
        close_btn.clicked.connect(lambda: self._on_close(self.drone_name))
        title_row.addWidget(close_btn)
        layout.addLayout(title_row)

        w, h = _fov_display_size(cfg.fov_h_deg, cfg.fov_v_deg, cfg.image_px)
        self._image_lbl = QLabel(_NO_FRAME_TEXT)
        self._image_lbl.setAlignment(Qt.AlignCenter)
        self._image_lbl.setFixedSize(w, h)
        self._image_lbl.setStyleSheet(f"color: {_DIM_COL}; background: #202020;")
        layout.addWidget(self._image_lbl)

        zoom_row = QHBoxLayout()
        self._zoom_lbl = QLabel("")
        self._zoom_lbl.setStyleSheet(f"color: {_TEXT_COL}; background: transparent;")
        zoom_row.addWidget(self._zoom_lbl)
        zoom_row.addStretch(1)
        self._zoom_out_btn = QPushButton("Zoom Out")
        self._zoom_out_btn.setStyleSheet(_BTN_STYLE)
        self._zoom_out_btn.clicked.connect(self._on_zoom_out)
        zoom_row.addWidget(self._zoom_out_btn)
        self._zoom_reset_btn = QPushButton("Reset")
        self._zoom_reset_btn.setStyleSheet(_BTN_STYLE)
        self._zoom_reset_btn.clicked.connect(self._on_zoom_reset)
        zoom_row.addWidget(self._zoom_reset_btn)
        self._zoom_in_btn = QPushButton("Zoom In")
        self._zoom_in_btn.setStyleSheet(_BTN_STYLE)
        self._zoom_in_btn.clicked.connect(self._on_zoom_in)
        zoom_row.addWidget(self._zoom_in_btn)
        layout.addLayout(zoom_row)

        camera_manager.frame_updated.connect(self._on_frame_updated)
        self.set_frame(camera_manager.get_frame(name))
        self._refresh_zoom_controls()
        self.adjustSize()

    def _mark_user_positioned(self) -> None:
        was_positioned = self._user_positioned
        self._user_positioned = True
        if not was_positioned:
            self._on_dragged(self.drone_name)

    def reposition(self, x: int, y: int) -> None:
        """Move to an exact top-left position — MapOverlay computes this
        from the map viewport plus this pane's home-slot index. No-op if
        the user has already dragged the pane away from its home slot."""
        self.raise_()
        if self._user_positioned:
            return
        self.adjustSize()
        self.move(x, y)

    def set_frame(self, pixmap: Optional[QPixmap]) -> None:
        _apply_frame(self._image_lbl, pixmap)

    def _refresh_zoom_controls(self) -> None:
        self._zoom_lbl.setText(f"Zoom: {self._mgr.get_zoom(self.drone_name):.1f}x")
        self._zoom_in_btn.setEnabled(self._mgr.can_zoom_in(self.drone_name))
        self._zoom_out_btn.setEnabled(self._mgr.can_zoom_out(self.drone_name))

    def _on_zoom_in(self) -> None:
        self._mgr.zoom_in(self.drone_name)
        self._refresh_zoom_controls()

    def _on_zoom_out(self) -> None:
        self._mgr.zoom_out(self.drone_name)
        self._refresh_zoom_controls()

    def _on_zoom_reset(self) -> None:
        self._mgr.zoom_reset(self.drone_name)
        self._refresh_zoom_controls()

    def _on_frame_updated(self, name: str) -> None:
        if name == self.drone_name:
            self.set_frame(self._mgr.get_frame(name))
            self._refresh_zoom_controls()
