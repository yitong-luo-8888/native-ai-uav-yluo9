"""
drone_panel.py — Dockable drone status panel.

DronePanel is a QWidget child of PanoOverlay, overlaid on the panorama
using absolute positioning within the parent's coordinate space.

Does NOT use QScrollArea (which creates a native X11 sub-window on WSL2/WSLg
and corrupts the parent's display pipeline).  A plain QWidget + QVBoxLayout
is used instead; Qt keeps it as an "alien" (non-native) widget sharing the
parent's X11 window.
"""

import time
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton,
)

from camera_manager import CameraManager, CameraMode
from drone import Drone

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
_PANEL_W          = 230   # px wide when docked left / right
_PANEL_H          = 130   # px tall when docked top / bottom
_BORDER_PX        = 4     # colored left-border strip on each card
_CARD_COLLAPSED_H = 74
_CARD_EXPANDED_H  = 290

_DARK_BG  = "rgba(30, 30, 30, 210)"
_CARD_BG  = "rgba(45, 45, 45, 240)"
_TEXT_COL = "#e8e8e8"
_DIM_COL  = "#999999"

_CAMERA_COLORS = {
    CameraMode.OFF:       "#777777",
    CameraMode.STREAMING: "#e04040",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lock_pixmap(size: int, color: QColor) -> QPixmap:
    """Outline padlock in the given drone colour, transparent background."""
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)

    stroke = max(1.2, size * 0.13)
    pen = QPen(color, stroke)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    m  = size * 0.12
    bt = size * 0.44

    # Body outline
    p.drawRoundedRect(QRectF(m, bt, size - 2*m, size - bt - m), size * 0.09, size * 0.09)

    # Keyhole dot
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(size * 0.50, size * 0.64), size * 0.08, size * 0.08)
    p.setBrush(Qt.NoBrush)
    p.setPen(pen)

    # Shackle arch + verticals
    sw  = size * 0.42
    sx  = (size - sw) / 2
    shy = size * 0.08
    shh = size * 0.50
    mid = shy + shh / 2
    p.drawArc(QRectF(sx, shy, sw, shh), 0 * 16, 180 * 16)
    p.drawLine(QPointF(sx,      mid), QPointF(sx,      bt))
    p.drawLine(QPointF(sx + sw, mid), QPointF(sx + sw, bt))

    p.end()
    return px


def _drone_color(name: str) -> QColor:
    c = QColor(name.lower())
    return c if c.isValid() else QColor(140, 140, 140)


def _heading_to_cardinal(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]


def _lbl(text: str, bold: bool = False, color: str = _TEXT_COL,
         align=Qt.AlignLeft) -> QLabel:
    w = QLabel(text)
    w.setAlignment(align)
    font = QFont("Segoe UI", 10)
    font.setBold(bold)
    w.setFont(font)
    w.setStyleSheet(f"color: {color}; background: transparent;")
    return w


# ---------------------------------------------------------------------------
# _DroneCard
# ---------------------------------------------------------------------------

class _DroneCard(QFrame):
    """
    One card per drone.  Collapsed by default; click header to expand.
    Call refresh(drone) each tick to update values without rebuilding widgets.
    """

    def __init__(self, drone: Drone, on_click,
                 camera_mgr: Optional[CameraManager] = None,
                 on_camera_click: Optional[Callable[[str], None]] = None,
                 parent: QWidget = None) -> None:
        super().__init__(parent)
        self._on_click = on_click
        self._camera_mgr = camera_mgr
        self._on_camera_click = on_camera_click
        self._camera_mode = CameraMode.OFF
        self.is_expanded = False
        color = _drone_color(drone.name)
        hex_color = color.name()

        self._drone_name      = drone.name

        self._home_alt:  Optional[float] = None   # altitude at arming → AGL reference
        self._prev_armed: Optional[bool] = None   # tracks arm/disarm transitions

        self._agl_flash_on = False
        self._agl_flash_timer = QTimer(self)
        self._agl_flash_timer.setInterval(500)
        self._agl_flash_timer.timeout.connect(self._on_agl_flash_tick)

        self.setObjectName("droneCard")
        self.setStyleSheet(f"""
            QFrame#droneCard {{
                background: {_CARD_BG};
                border-left: {_BORDER_PX}px solid {hex_color};
                border-top: 1px solid #555;
            }}
        """)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 4, 4)
        outer.setSpacing(0)

        # --- Collapsed header ---
        self._name_lbl = _lbl(drone.name.upper(), bold=True, color=hex_color)
        self._name_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._mode_lbl = _lbl("", color=_DIM_COL)
        self._task_lbl = _lbl("", color=_TEXT_COL)
        self._task_lbl.setWordWrap(True)

        # Camera button — shown only when a CameraManager is attached (simulation mode)
        self._camera_btn = QPushButton("C")
        self._camera_btn.setFixedSize(22, 22)
        self._camera_btn.setCursor(Qt.PointingHandCursor)
        self._camera_btn.clicked.connect(self._on_camera_clicked)
        self._apply_camera_style()
        self._camera_btn.setVisible(self._camera_mgr is not None)

        # Lock icon — shown when LEASE_DENIED for ≥ 2 s; hidden after restored ≥ 1 s
        _LOCK = 18
        self._lock_lbl = QLabel()
        self._lock_lbl.setPixmap(_lock_pixmap(_LOCK, color))
        self._lock_lbl.setFixedSize(_LOCK, _LOCK)
        self._lock_lbl.setStyleSheet("background: transparent;")
        self._lock_lbl.setToolTip("Air lease denied")
        self._lock_lbl.hide()

        self._deny_start:    Optional[float] = None
        self._restore_start: Optional[float] = None
        self._lock_visible:  bool            = False

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(4)
        name_row.addWidget(self._name_lbl, 1)
        name_row.addWidget(self._lock_lbl)
        name_row.addWidget(self._camera_btn)

        outer.addLayout(name_row)
        outer.addWidget(self._mode_lbl)
        outer.addWidget(self._task_lbl)

        # --- Expanded section ---
        self._exp_widget = QWidget()
        self._exp_widget.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(self._exp_widget)
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setSpacing(1)

        self._exp_labels: Dict[str, QLabel] = {}
        for key in ("Status", "Armed", "Heartbeat", "Air Lease",
                    "Geofence", "State Type",
                    "Lat", "Lon", "Altitude", "Heading", "Speed", "Battery"):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            k_lbl = _lbl(key, color=_DIM_COL)
            k_lbl.setFixedWidth(82)
            k_lbl.setFont(QFont("Segoe UI", 9))
            v_lbl = _lbl("—", color=_TEXT_COL)
            v_lbl.setFont(QFont("Segoe UI", 9))
            row.addWidget(k_lbl)
            row.addWidget(v_lbl, 1)
            grid.addLayout(row)
            self._exp_labels[key] = v_lbl

        outer.addWidget(self._exp_widget)
        self._exp_widget.setVisible(False)

        self.setFixedHeight(_CARD_COLLAPSED_H)
        self.refresh(drone)

    # ------------------------------------------------------------------

    def _apply_camera_style(self) -> None:
        col = _CAMERA_COLORS[self._camera_mode]
        self._camera_btn.setToolTip(f"Camera: {self._camera_mode.value}")
        self._camera_btn.setStyleSheet(f"""
            QPushButton {{
                color: {col};
                background: transparent;
                border: 1px solid {col};
                border-radius: 3px;
                font-size: 10px;
                font-weight: bold;
                padding: 0px;
            }}
        """)

    def _on_camera_clicked(self) -> None:
        if self._on_camera_click is not None:
            self._on_camera_click(self._drone_name)

    def set_expanded(self, expanded: bool) -> None:
        self.is_expanded = expanded
        self._exp_widget.setVisible(expanded)
        self.setFixedHeight(_CARD_EXPANDED_H if expanded else _CARD_COLLAPSED_H)

    def refresh(self, d: Drone) -> None:
        # --- Air-lease lock icon with debounce timers ---
        now    = time.monotonic()
        denied = d.air_lease_state == "LEASE_DENIED"
        if denied:
            self._restore_start = None
            if self._deny_start is None:
                self._deny_start = now
            if not self._lock_visible and (now - self._deny_start) >= 2.0:
                self._lock_lbl.show()
                self._lock_visible = True
        else:
            self._deny_start = None
            if self._lock_visible:
                if self._restore_start is None:
                    self._restore_start = now
                if (now - self._restore_start) >= 1.0:
                    self._lock_lbl.hide()
                    self._lock_visible  = False
                    self._restore_start = None

        self._task_lbl.setText(d.onboard_pilot or "—")

        heading_deg = d.heading_rad % 360   # MQTT delivers degrees directly

        # --- Home altitude tracking (AGL reference) ---
        was_armed = self._prev_armed
        self._prev_armed = d.armed
        if d.armed is True and was_armed is not True:
            self._home_alt = d.alt          # record ground level on arm
        elif d.armed is False and was_armed is True:
            self._home_alt = None           # clear on disarm

        # --- Mode label with direction + AGL suffix ---
        mode = d.mode or "—"
        cardinal = _heading_to_cardinal(heading_deg)
        if self._home_alt is not None:
            agl = d.alt - self._home_alt
            self._mode_lbl.setText(f"{mode}: {cardinal} @ {agl:.1f}m AGL")
            if agl > 121:
                if not self._agl_flash_timer.isActive():
                    self._agl_flash_on = False
                    self._agl_flash_timer.start()
            else:
                if self._agl_flash_timer.isActive():
                    self._agl_flash_timer.stop()
                    self._mode_lbl.setStyleSheet(
                        f"color: {_DIM_COL}; background: transparent;")
        else:
            if self._agl_flash_timer.isActive():
                self._agl_flash_timer.stop()
                self._mode_lbl.setStyleSheet(
                    f"color: {_DIM_COL}; background: transparent;")
            self._mode_lbl.setText(f"{mode}: {cardinal}, On Ground")

        def _yn(v):        return "Yes" if v else "No"

        self._exp_labels["Status"].setText(d.status or "—")
        self._exp_labels["Armed"].setText(_yn(d.armed) if d.armed is not None else "—")
        self._exp_labels["Heartbeat"].setText(d.heartbeat_status or "—")
        self._exp_labels["Air Lease"].setText(d.air_lease_state or "—")
        self._exp_labels["Geofence"].setText(
            ("Active" if d.geofence else "Clear") if d.geofence is not None else "—"
        )
        self._exp_labels["State Type"].setText(d.state_type or "—")
        self._exp_labels["Lat"].setText(f"{d.lat:.6f}")
        self._exp_labels["Lon"].setText(f"{d.lon:.6f}")
        self._exp_labels["Altitude"].setText(f"{d.alt:.1f} m")
        self._exp_labels["Heading"].setText(
            f"{heading_deg:.1f}°  {_heading_to_cardinal(heading_deg)}"
        )
        self._exp_labels["Speed"].setText(
            f"{d.speed:.2f} m/s" if d.speed is not None else "—"
        )
        pct  = f"{d.battery_level * 100:.0f}%"
        volt = f"{d.voltage:.1f}V"
        amp  = f"{d.battery_current:.1f}A" if d.battery_current is not None else ""
        self._exp_labels["Battery"].setText(
            "  ".join(x for x in (pct, volt, amp) if x)
        )

        if self._camera_mgr is not None:
            mode = self._camera_mgr.get_mode(self._drone_name)
            if mode != self._camera_mode:
                self._camera_mode = mode
                self._apply_camera_style()

    def _on_agl_flash_tick(self) -> None:
        self._agl_flash_on = not self._agl_flash_on
        color = "#ff3333" if self._agl_flash_on else "#ff9090"
        self._mode_lbl.setStyleSheet(f"color: {color}; background: transparent;")

    # ------------------------------------------------------------------
    # Mouse: click to expand

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(ev)


# ---------------------------------------------------------------------------
# DronePanel
# ---------------------------------------------------------------------------

class DronePanel(QWidget):
    """
    Overlay panel anchored to one edge of the parent PanoOverlay widget.

    Implemented as a child widget (not a top-level window) so it is visually
    part of the main window.  Uses only plain QWidget + QVBoxLayout — no
    QScrollArea — to avoid native X11 sub-window creation on WSL2/WSLg.

    Call reposition() whenever the parent is resized or moved.
    """

    def __init__(self, parent: QWidget, side: str = "right",
                 camera_manager: Optional[CameraManager] = None,
                 on_camera_click: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(parent)
        self._side = side
        self._cards: Dict[str, _DroneCard] = {}
        self._expanded: List[str] = []   # FIFO queue, max 3
        self._on_camera_click = on_camera_click
        self._camera_manager = camera_manager

        # WA_StyledBackground is required for background colour on a child QWidget
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {_DARK_BG};")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)
        self._layout.addStretch(1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_drones(self, drones: List[Drone]) -> None:
        """Add/remove/refresh cards to match current drone list."""
        current_names = {d.name for d in drones}
        existing_names = set(self._cards.keys())

        for name in existing_names - current_names:
            card = self._cards.pop(name)
            self._layout.removeWidget(card)
            card.deleteLater()
            if name in self._expanded:
                self._expanded.remove(name)

        stretch_idx = self._layout.count() - 1  # insert before the trailing stretch
        for d in drones:
            if d.name not in self._cards:
                card = _DroneCard(
                    d,
                    on_click=lambda n=d.name: self._on_card_clicked(n),
                    camera_mgr=self._camera_manager,
                    on_camera_click=self._on_camera_click,
                    parent=self,
                )
                self._cards[d.name] = card
                self._layout.insertWidget(stretch_idx, card)
                stretch_idx += 1

        for d in drones:
            if d.name in self._cards:
                self._cards[d.name].refresh(d)

    def reposition(self) -> None:
        """Snap geometry to the current dock side within the parent widget."""
        p = self.parent()
        pw, ph = p.width(), p.height()

        if self._side == "right":
            self.setGeometry(pw - _PANEL_W, 0, _PANEL_W, ph)
        elif self._side == "left":
            self.setGeometry(0, 0, _PANEL_W, ph)
        elif self._side == "top":
            self.setGeometry(0, 0, pw, _PANEL_H)
        elif self._side == "bottom":
            self.setGeometry(0, ph - _PANEL_H, pw, _PANEL_H)

        self.raise_()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    _MAX_EXPANDED = 3

    def _on_card_clicked(self, name: str) -> None:
        """Toggle expansion; up to 3 cards open at once, FIFO collapse."""
        card = self._cards.get(name)
        if card is None:
            return

        if card.is_expanded:
            # Collapse this card
            card.set_expanded(False)
            if name in self._expanded:
                self._expanded.remove(name)
        else:
            # Expand this card; evict oldest if at limit
            if len(self._expanded) >= self._MAX_EXPANDED:
                oldest = self._expanded.pop(0)
                if oldest in self._cards:
                    self._cards[oldest].set_expanded(False)
            card.set_expanded(True)
            self._expanded.append(name)
