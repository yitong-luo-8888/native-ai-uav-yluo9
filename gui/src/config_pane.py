"""
config_pane.py — Configuration panel.

Currently exposes:
  • Satellite imagery source
  • Map orientation (fixed heading, or pick from map)
"""

from PyQt5.QtCore    import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

_RIBBON_W = 48   # must match tool_ribbon._RIBBON_W
_PANE_W   = 280


class ConfigPane(QWidget):
    """
    Narrow inline pane shown to the right of the ribbon when ⚙ is active.
    """

    map_heading_changed    = pyqtSignal(int)    # emitted when operator heading changes (0-360°)
    tile_provider_changed  = pyqtSignal(str)    # emitted when satellite imagery source changes
    start_heading_pick     = pyqtSignal()       # From Map mode activated — enter two-click pick
    cancel_heading_pick    = pyqtSignal()       # leaving From Map mode — cancel pick or arrow
    accept_heading_arrow   = pyqtSignal()       # user confirmed the alignment arrow

    _BG   = "rgba(20, 20, 30, 210)"
    _TEXT = "#e8e8e8"

    _MODE_ON = (
        "QPushButton { background: rgba(60,100,160,200); color: #ddd;"
        " border: none; border-radius: 4px; padding: 3px 8px; font-size: 10px; }"
    )
    _MODE_OFF = (
        "QPushButton { background: rgba(50,50,70,160); color: #888;"
        " border: none; border-radius: 4px; padding: 3px 8px; font-size: 10px; }"
        "QPushButton:hover { background: rgba(60,60,85,200); color: #bbb; }"
    )

    def __init__(
        self,
        parent=None,
        tile_provider: str = "clarity",
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {self._BG}; color: {self._TEXT};")

        _grp_style = (
            "QGroupBox {"
            "  color: #9090aa; border: 1px solid #2a2a44;"
            "  border-radius: 4px; margin-top: 8px; padding-top: 10px;"
            "  font-size: 10px;"
            "}"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
            "QWidget { background: transparent; }"
        )
        vl = QVBoxLayout(self)
        vl.setContentsMargins(12, 14, 12, 12)
        vl.setSpacing(12)

        # ---- title ----
        title = QLabel("Configuration")
        title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #ffffff;"
            " background: transparent;"
        )
        vl.addWidget(title)

        # ---- Map Layers group ----
        layers_grp = QGroupBox("Map Layers")
        layers_grp.setStyleSheet(_grp_style)
        ll = QVBoxLayout(layers_grp)
        ll.setSpacing(6)

        # ---- Satellite imagery source ----
        sat_label = QLabel("Satellite imagery")
        sat_label.setStyleSheet("color: #ddddee; font-size: 11px; background: transparent;")
        ll.addWidget(sat_label)

        _providers = [
            ("Standard (cloud-composited)", "standard"),
            ("Clarity (sharper, orthographic)", "clarity"),
        ]
        self._tile_combo = QComboBox()
        self._tile_combo.setStyleSheet(
            "QComboBox { color: #ddddee; background: #1a1a2a; border: 1px solid #2a2a44;"
            " border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            "QComboBox::drop-down { width: 18px; }"
            "QComboBox QAbstractItemView { background: #1a1a2a; color: #ddddee;"
            " selection-background-color: #2a2a4a; }"
        )
        for label, key in _providers:
            self._tile_combo.addItem(label, key)
        default_idx = next(
            (i for i, (_, k) in enumerate(_providers) if k == tile_provider), 0
        )
        self._tile_combo.setCurrentIndex(default_idx)
        self._tile_combo.currentIndexChanged.connect(
            lambda _: self.tile_provider_changed.emit(self._tile_combo.currentData())
        )
        ll.addWidget(self._tile_combo)

        vl.addWidget(layers_grp)

        # ---- Map Orientation group ----
        orient_grp = QGroupBox("Map Orientation")
        orient_grp.setStyleSheet(_grp_style)
        ol = QVBoxLayout(orient_grp)
        ol.setSpacing(8)

        # Mode selector row
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self._orient_degrees_btn = QPushButton("Degrees")
        self._orient_pick_btn    = QPushButton("From Map")
        self._orient_reset_btn   = QPushButton("Reset")
        self._orient_degrees_btn.setStyleSheet(self._MODE_ON)
        self._orient_pick_btn.setStyleSheet(self._MODE_OFF)
        self._orient_reset_btn.setStyleSheet(self._MODE_OFF)
        self._orient_degrees_btn.clicked.connect(lambda: self._set_orient_mode("degrees"))
        self._orient_pick_btn.clicked.connect(lambda: self._set_orient_mode("pick"))
        self._orient_reset_btn.clicked.connect(self._reset_heading)
        mode_row.addWidget(self._orient_degrees_btn)
        mode_row.addWidget(self._orient_pick_btn)
        mode_row.addWidget(self._orient_reset_btn)
        mode_row.addStretch()
        ol.addLayout(mode_row)

        # --- Degrees sub-widget ---
        self._degrees_widget = QWidget()
        self._degrees_widget.setStyleSheet("background: transparent;")
        dw = QVBoxLayout(self._degrees_widget)
        dw.setContentsMargins(0, 0, 0, 0)
        dw.setSpacing(4)

        orient_hint = QLabel("Operator heading (degrees)")
        orient_hint.setStyleSheet("color: #ddddee; font-size: 11px; background: transparent;")
        dw.addWidget(orient_hint)

        spin_row = QHBoxLayout()
        self._heading_spin = QSpinBox()
        self._heading_spin.setRange(0, 360)
        self._heading_spin.setValue(0)
        self._heading_spin.setSuffix("°")
        self._heading_spin.setToolTip(
            "Rotate the map so that this compass direction faces the top of the screen.\n"
            "0° and 360° = North up (default). 90° = East up. 180° = South up."
        )
        self._heading_spin.setStyleSheet(
            "QSpinBox { color: #ddddee; background: #1a1a2a; border: 1px solid #2a2a44;"
            " border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 16px; }"
        )
        self._heading_spin.valueChanged.connect(self.map_heading_changed)
        spin_row.addWidget(self._heading_spin)
        spin_row.addStretch()
        dw.addLayout(spin_row)

        orient_note = QLabel("0° / 360° = North  •  90° = East\n180° = South  •  270° = West")
        orient_note.setStyleSheet("color: #666677; font-size: 9px; background: transparent;")
        dw.addWidget(orient_note)

        ol.addWidget(self._degrees_widget)

        # --- From Map sub-widget ---
        self._pick_widget = QWidget()
        self._pick_widget.setStyleSheet("background: transparent;")
        pw = QVBoxLayout(self._pick_widget)
        pw.setContentsMargins(0, 0, 0, 0)
        pw.setSpacing(4)

        self._pick_hint_lbl = QLabel("Click your position on the map")
        self._pick_hint_lbl.setStyleSheet(
            "color: #aaaacc; font-size: 11px; background: transparent;"
        )
        self._pick_hint_lbl.setWordWrap(True)
        pw.addWidget(self._pick_hint_lbl)

        self._align_btn = QPushButton("Align Map")
        self._align_btn.setStyleSheet(self._MODE_ON)
        self._align_btn.clicked.connect(self.accept_heading_arrow)
        pw.addWidget(self._align_btn)
        self._align_btn.hide()

        self._cancel_align_btn = QPushButton("Cancel Realignment")
        self._cancel_align_btn.setStyleSheet(self._MODE_OFF)
        self._cancel_align_btn.clicked.connect(self.cancel_heading_pick)
        pw.addWidget(self._cancel_align_btn)
        self._cancel_align_btn.hide()

        ol.addWidget(self._pick_widget)
        self._pick_widget.hide()

        vl.addWidget(orient_grp)
        vl.addStretch()

    # ------------------------------------------------------------------ #

    def _set_orient_mode(self, mode: str) -> None:
        # Cancel any in-progress pick when leaving From Map mode
        if mode != "pick" and self._pick_widget.isVisible():
            self.cancel_heading_pick.emit()

        is_pick = mode == "pick"
        self._orient_degrees_btn.setStyleSheet(
            self._MODE_ON if mode == "degrees" else self._MODE_OFF
        )
        self._orient_pick_btn.setStyleSheet(self._MODE_ON if is_pick else self._MODE_OFF)
        self._orient_reset_btn.setStyleSheet(self._MODE_OFF)  # never stays highlighted
        self._degrees_widget.setVisible(mode == "degrees")
        self._pick_widget.setVisible(is_pick)

        if is_pick:
            self._pick_hint_lbl.setText("Click your position on the map")
            self._align_btn.hide()
            self._cancel_align_btn.hide()
            self.start_heading_pick.emit()

    def _reset_heading(self) -> None:
        self._set_orient_mode("degrees")
        self._heading_spin.setValue(0)

    def on_heading_pick_step(self, step: int) -> None:
        if step == 1:
            self._pick_hint_lbl.setText("Now click a point in your viewing direction")

    def on_heading_arrow_shown(self) -> None:
        self._pick_hint_lbl.setText(
            "Drag the arrowhead to adjust,\nor double-click it to accept"
        )
        self._align_btn.show()
        self._cancel_align_btn.show()

    def set_heading_from_pick(self, degrees: int) -> None:
        """Called after a successful two-click pick; updates spinbox and returns to Degrees mode."""
        self._set_orient_mode("degrees")
        self._heading_spin.setValue(degrees)

    @property
    def map_heading(self) -> int:
        return self._heading_spin.value()

    def set_tile_provider(self, key: str) -> None:
        """Set the tile provider combo silently (no signal emitted)."""
        idx = self._tile_combo.findData(key)
        if idx >= 0 and idx != self._tile_combo.currentIndex():
            self._tile_combo.blockSignals(True)
            self._tile_combo.setCurrentIndex(idx)
            self._tile_combo.blockSignals(False)

    @property
    def tile_provider(self) -> str:
        return self._tile_combo.currentData()

    def reposition(self) -> None:
        p = self.parent()
        self.setGeometry(_RIBBON_W, 0, _PANE_W, p.height())
        self.raise_()
