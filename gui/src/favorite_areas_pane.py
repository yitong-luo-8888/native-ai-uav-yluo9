"""
favorite_areas_pane.py — Overlay pane for managing favorite map areas.

Each area has a name, tag, lat, lon, and altitude ASL.
One area may be marked as DEFAULT; it is applied automatically at startup.

Curated areas live in favorite_areas.json (tracked in git — course sites,
anything meant to ship to every student). Areas added through the
"+ Add area" form live in favorite_areas.local.json instead (gitignored —
personal, per-machine, never committed). Both are merged transparently by
_load_areas(); _save_areas() splits them back apart by origin so edits to
one never bleed into the other.

on_area_selected(area: dict), if provided, is called when the user clicks
"Go" or when apply_default() is called at startup.
"""

import json
from pathlib import Path

from PyQt5.QtCore    import Qt, QPointF, QSize
from PyQt5.QtGui     import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QDoubleSpinBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

_AREAS_FILE       = Path(__file__).parent / "favorite_areas.json"
_LOCAL_AREAS_FILE = Path(__file__).parent / "favorite_areas.local.json"
_ORIGIN_KEY       = "_origin"   # transient in-memory tag; never written to disk
_RIBBON_W   = 48       # must match tool_ribbon._RIBBON_W
_PANE_W     = 320

_BG      = "rgba(20, 20, 30, 210)"
_CARD_BG = "rgba(40, 40, 55, 230)"
_TEXT    = "#e8e8e8"
_DIM     = "#888888"

_PANE_STYLE = "QWidget#favAreasPane { background: rgba(20, 20, 30, 210); }"
_CARD_STYLE = "QFrame#areaRow { background: rgba(40, 40, 55, 230); border-radius: 4px; }"
_FORM_STYLE = (
    "QFrame#addAreaForm {"
    "  background: rgba(30, 35, 50, 240);"
    "  border: 1px solid rgba(255,255,255,25);"
    "  border-radius: 4px;"
    "}"
    "QLabel { color: #aaa; font-size: 11px; background: transparent; }"
    "QLineEdit, QDoubleSpinBox {"
    "  background: rgba(50,50,70,220);"
    "  color: #ddd;"
    "  border: 1px solid rgba(255,255,255,40);"
    "  border-radius: 4px;"
    "  padding: 3px 6px;"
    "  font-size: 12px;"
    "}"
)

_ADD_STYLE = (
    "QPushButton {"
    "  background: rgba(60,100,160,200);"
    "  color: #ddd; border: none; border-radius: 4px;"
    "  padding: 5px 8px; font-size: 12px;"
    "}"
    "QPushButton:hover { background: rgba(80,130,200,220); }"
)

_PIN_BTN_STYLE = (
    "QPushButton { background: transparent; border: none; padding: 2px; }"
    "QPushButton:hover { background: rgba(255,255,255,18); border-radius: 4px; }"
)


def _pin_pixmap(size: int, active: bool) -> QPixmap:
    """Map-pin icon. Active (shown) = bright blue filled; inactive = dim."""
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)

    cx   = size * 0.50
    cy   = size * 0.36   # centre of the pin head
    r    = size * 0.30   # head radius
    tip  = QPointF(cx, size * 0.90)

    if active:
        fill    = QColor(50,  115, 210, 235)
        outline = QColor(100, 165, 255, 220)
        dot_col = QColor(215, 235, 255, 210)
    else:
        fill    = QColor(68, 72, 92, 175)
        outline = QColor(105, 110, 138, 195)
        dot_col = None

    # Triangle tail
    tail = QPainterPath()
    tail.moveTo(tip)
    tail.lineTo(cx - r * 0.72, cy + r * 0.55)
    tail.lineTo(cx + r * 0.72, cy + r * 0.55)
    tail.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(fill)
    p.drawPath(tail)

    # Pin head (circle)
    p.setPen(QPen(outline, 0.9))
    p.setBrush(fill)
    p.drawEllipse(QPointF(cx, cy), r, r)

    # Inner highlight dot for active
    if dot_col:
        p.setPen(Qt.NoPen)
        p.setBrush(dot_col)
        p.drawEllipse(QPointF(cx, cy), r * 0.38, r * 0.38)

    p.end()
    return px

_DELETE_STYLE = (
    "QPushButton {"
    "  background: transparent;"
    "  color: #555568;"
    "  border: none;"
    "  border-radius: 3px;"
    "  padding: 2px 5px;"
    "  font-size: 14px;"
    "}"
    "QPushButton:hover { color: rgba(80,130,200,230); background: rgba(36,58,110,60); }"
    "QPushButton:pressed { color: rgba(110,160,230,255); }"
)

_CONFIRM_STYLE = (
    "QWidget#confirmBar {"
    "  background: rgba(22, 28, 45, 220);"
    "  border-top: 1px solid rgba(60,100,160,80);"
    "  border-radius: 0px;"
    "}"
    "QLabel { color: rgba(130,170,220,220); font-size: 11px; background: transparent; }"
)

_CONFIRM_YES_STYLE = (
    "QPushButton {"
    "  background: rgba(36,60,110,220);"
    "  color: rgba(130,180,240,230);"
    "  border: 1px solid rgba(60,100,160,160);"
    "  border-radius: 3px;"
    "  padding: 2px 10px; font-size: 11px;"
    "}"
    "QPushButton:hover { background: rgba(46,80,140,230); border-color: rgba(80,130,200,200); }"
)

_CONFIRM_NO_STYLE = (
    "QPushButton {"
    "  background: transparent;"
    "  color: #777788;"
    "  border: 1px solid #44445a;"
    "  border-radius: 3px;"
    "  padding: 2px 10px; font-size: 11px;"
    "}"
    "QPushButton:hover { color: #aaaacc; border-color: #666688; }"
)


_SAVE_STYLE = (
    "QPushButton {"
    "  background: rgba(60,100,160,200);"
    "  color: #ddd; border: none; border-radius: 4px;"
    "  padding: 4px 12px; font-size: 11px;"
    "}"
    "QPushButton:hover { background: rgba(80,130,200,220); }"
)

_CANCEL_STYLE = (
    "QPushButton {"
    "  background: rgba(50,50,65,200);"
    "  color: #aaa; border: none; border-radius: 4px;"
    "  padding: 4px 12px; font-size: 11px;"
    "}"
    "QPushButton:hover { background: rgba(70,70,90,220); color: #ccc; }"
)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with path.open() as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _load_areas() -> list:
    """Curated areas (favorite_areas.json) first, then personal ones
    (favorite_areas.local.json), tagged with their origin so _save_areas
    can write each back to the right file."""
    shared = _load_json_list(_AREAS_FILE)
    local  = _load_json_list(_LOCAL_AREAS_FILE)
    for a in shared:
        a[_ORIGIN_KEY] = "shared"
    for a in local:
        a[_ORIGIN_KEY] = "local"
    return shared + local


def _save_areas(areas: list) -> None:
    """Split back into shared vs. personal by origin tag and write each
    half to its own file. Areas with no tag (freshly created, not yet
    round-tripped through _load_areas) are treated as personal — only
    entries that started out in favorite_areas.json stay there."""
    def _untagged(lst):
        out = []
        for a in lst:
            b = dict(a)
            b.pop(_ORIGIN_KEY, None)
            out.append(b)
        return out

    shared = _untagged(a for a in areas if a.get(_ORIGIN_KEY) == "shared")
    local  = _untagged(a for a in areas if a.get(_ORIGIN_KEY) != "shared")

    with _AREAS_FILE.open("w") as fh:
        json.dump(shared, fh, indent=2)

    if local:
        with _LOCAL_AREAS_FILE.open("w") as fh:
            json.dump(local, fh, indent=2)
    elif _LOCAL_AREAS_FILE.exists():
        _LOCAL_AREAS_FILE.unlink()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_divider(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    line.setStyleSheet("color: rgba(255,255,255,40);")
    line.setFixedHeight(1)
    return line


# ---------------------------------------------------------------------------
# _AddAreaForm  — inline expandable form, lives in the pane layout
# ---------------------------------------------------------------------------

class _AddAreaForm(QFrame):
    """Inline form shown under the '+ Add area' button. Hidden by default."""

    def __init__(self, on_save, on_cancel, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("addAreaForm")
        self.setStyleSheet(_FORM_STYLE)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._on_save   = on_save
        self._on_cancel = on_cancel

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. North Campus")

        self._tag_edit = QLineEdit()
        self._tag_edit.setPlaceholderText("e.g. north-campus")

        self._latlon_edit = QLineEdit()
        self._latlon_edit.setPlaceholderText("e.g. 41.7554, -86.1910")

        self._alt_spin = QDoubleSpinBox()
        self._alt_spin.setRange(-500.0, 9000.0)
        self._alt_spin.setDecimals(1)
        self._alt_spin.setSuffix(" m ASL")
        self._alt_spin.setValue(0.0)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(5)
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow("Name:",    self._name_edit)
        form.addRow("Tag:",     self._tag_edit)
        form.addRow("Lat, Lon:", self._latlon_edit)
        form.addRow("Alt:",     self._alt_spin)

        btn_save = QPushButton("Save")
        btn_save.setStyleSheet(_SAVE_STYLE)
        self._save_cb = lambda: self._commit()
        btn_save.clicked.connect(self._save_cb)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(_CANCEL_STYLE)
        self._cancel_cb = lambda: on_cancel()
        btn_cancel.clicked.connect(self._cancel_cb)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(5)
        layout.addLayout(form)
        layout.addLayout(btn_row)

        self.hide()

    def clear(self) -> None:
        self._name_edit.clear()
        self._tag_edit.clear()
        self._latlon_edit.clear()
        self._alt_spin.setValue(0.0)

    def _parse_latlon(self) -> tuple:
        text = self._latlon_edit.text().strip()
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])
        raise ValueError("need two values")

    def _commit(self) -> None:
        try:
            lat, lon = self._parse_latlon()
        except ValueError:
            QMessageBox.warning(self, "Invalid coordinates",
                                "Enter as:  lat, lon\ne.g. 41.755404, -86.191016")
            return
        area = {
            "name":     self._name_edit.text().strip() or "Unnamed",
            "tag":      self._tag_edit.text().strip(),
            "lat":      lat,
            "lon":      lon,
            "altitude": self._alt_spin.value(),
            "default":  False,
        }
        self._on_save(area)


# ---------------------------------------------------------------------------
# AreaRow
# ---------------------------------------------------------------------------

class AreaRow(QFrame):
    """One card per favorite area."""

    def __init__(
        self,
        area: dict,
        index: int,
        on_show,              # callable(area)
        on_delete,            # callable(index)
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("areaRow")
        self.setStyleSheet(_CARD_STYLE)

        self._area  = area
        self._index = index

        # ---- Left: name, tag, coords ------------------------------------
        name_lbl = QLabel(area.get("name", "?"))
        name_font = QFont("Segoe UI", 10)
        name_font.setBold(True)
        name_lbl.setFont(name_font)
        name_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent;")

        tag = area.get("tag", "")
        tag_lbl = QLabel(tag if tag else "")
        tag_lbl.setStyleSheet(f"color: {_DIM}; font-size: 10px; background: transparent;")

        lat = area.get("lat", 0.0)
        lon = area.get("lon", 0.0)
        alt = area.get("altitude", 0.0)
        coord_lbl = QLabel(f"{lat:.6f},  {lon:.6f}  \u2022  {alt:.0f}\u202fm ASL")
        coord_lbl.setStyleSheet(f"color: {_DIM}; font-size: 9px; background: transparent;")

        left_box = QVBoxLayout()
        left_box.setContentsMargins(6, 4, 4, 4)
        left_box.setSpacing(2)
        left_box.addWidget(name_lbl)
        if tag:
            left_box.addWidget(tag_lbl)
        left_box.addWidget(coord_lbl)

        # ---- Right: pin icon + delete -----------------------------------
        _PIN_SIZE = 26
        self._btn_go = QPushButton()
        self._btn_go.setStyleSheet(_PIN_BTN_STYLE)
        self._btn_go.setFixedSize(_PIN_SIZE, _PIN_SIZE)
        self._btn_go.setIconSize(QSize(_PIN_SIZE - 4, _PIN_SIZE - 4))
        self._btn_go.setIcon(QIcon(_pin_pixmap(_PIN_SIZE - 4, False)))
        self._on_go_cb = lambda: on_show(self._area)
        self._btn_go.clicked.connect(self._on_go_cb)

        self._btn_del = QPushButton("\u00d7")   # ×
        self._btn_del.setStyleSheet(_DELETE_STYLE)
        self._btn_del.setFixedWidth(24)
        self._btn_del.setToolTip("Remove this area")
        self._on_del_click_cb = lambda: self._show_confirm()
        self._btn_del.clicked.connect(self._on_del_click_cb)

        right_hl = QHBoxLayout()
        right_hl.setContentsMargins(4, 4, 6, 4)
        right_hl.setSpacing(4)
        right_hl.addWidget(self._btn_go)
        right_hl.addWidget(self._btn_del)

        # ---- Confirmation bar (hidden until × clicked) ------------------
        self._confirm_bar = QWidget(self)
        self._confirm_bar.setObjectName("confirmBar")
        self._confirm_bar.setStyleSheet(_CONFIRM_STYLE)

        confirm_lbl = QLabel("Confirm delete?")

        btn_yes = QPushButton("Delete")
        btn_yes.setStyleSheet(_CONFIRM_YES_STYLE)
        self._on_yes_cb = lambda: on_delete(self._index)
        btn_yes.clicked.connect(self._on_yes_cb)

        btn_no = QPushButton("Cancel")
        btn_no.setStyleSheet(_CONFIRM_NO_STYLE)
        self._on_no_cb = lambda: self._hide_confirm()
        btn_no.clicked.connect(self._on_no_cb)

        confirm_hl = QHBoxLayout(self._confirm_bar)
        confirm_hl.setContentsMargins(8, 4, 6, 4)
        confirm_hl.setSpacing(6)
        confirm_hl.addWidget(confirm_lbl)
        confirm_hl.addStretch()
        confirm_hl.addWidget(btn_yes)
        confirm_hl.addWidget(btn_no)

        self._confirm_bar.hide()

        # ---- Assemble ---------------------------------------------------
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addLayout(left_box, stretch=1)
        row.addLayout(right_hl)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addLayout(row)
        main.addWidget(self._confirm_bar)

    def _show_confirm(self) -> None:
        self._btn_del.setEnabled(False)
        self._confirm_bar.show()

    def _hide_confirm(self) -> None:
        self._confirm_bar.hide()
        self._btn_del.setEnabled(True)

    def set_active(self, value: bool) -> None:
        sz = self._btn_go.iconSize().width()
        self._btn_go.setIcon(QIcon(_pin_pixmap(sz, value)))
        self._btn_go.setEnabled(not value)


# ---------------------------------------------------------------------------
# FavoriteAreasPane
# ---------------------------------------------------------------------------

class FavoriteAreasPane(QWidget):
    """
    Semi-transparent overlay pane listing favorite map areas.
    Positioned just right of the ribbon.

    on_area_selected(area: dict) is called when the user clicks "Go" or
    when apply_default() selects the default area at startup.
    """

    def __init__(self, tile_map, on_area_selected=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("favAreasPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_PANE_STYLE)

        self._tile_map         = tile_map
        self._on_area_selected = on_area_selected
        self._rows: list       = []

        # ---- Title ---------------------------------------------------------
        title = QLabel("Favorite Areas")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold; background: transparent;"
        )

        # ---- Add button ----------------------------------------------------
        self._btn_add = QPushButton("+ Add area")
        self._btn_add.setStyleSheet(_ADD_STYLE)
        self._btn_add.clicked.connect(self._on_add)

        # ---- Inline add form (hidden until user clicks + Add area) ---------
        self._add_form = _AddAreaForm(
            on_save=self._on_add_save,
            on_cancel=self._on_add_cancel,
            parent=self,
        )

        # ---- Row container -------------------------------------------------
        self._row_container = QWidget(self)
        self._row_container.setStyleSheet("background: transparent;")
        self._row_layout = QVBoxLayout(self._row_container)
        self._row_layout.setContentsMargins(4, 0, 4, 0)
        self._row_layout.setSpacing(4)

        # ---- Main layout ---------------------------------------------------
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(6)
        main.addWidget(title)
        main.addWidget(self._btn_add)
        main.addWidget(self._add_form)
        main.addWidget(_make_divider(self))
        main.addWidget(self._row_container)
        main.addStretch(1)

        self.hide()
        self._rebuild()

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def reposition(self) -> None:
        p = self.parent()
        self.setGeometry(_RIBBON_W, 0, _PANE_W, p.height())
        self.raise_()

    def apply_default(self) -> None:
        """Navigate to the default area; called once at startup."""
        for area in _load_areas():
            if area.get("default", False):
                self._go(area)
                return

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _rebuild(self) -> None:
        for row in self._rows:
            self._row_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        for i, area in enumerate(_load_areas()):
            row = AreaRow(
                area=area,
                index=i,
                on_show=self._go,
                on_delete=self._on_delete,
                parent=self._row_container,
            )
            self._row_layout.addWidget(row)
            self._rows.append(row)

    def _go(self, area: dict) -> None:
        for row in self._rows:
            row.set_active(row._area is area)
        # Remember last-used as the default
        areas = _load_areas()
        area_name = area.get("name")
        for a in areas:
            a["default"] = (a.get("name") == area_name)
        _save_areas(areas)
        self._tile_map.set_center(area.get("lat", 0.0), area.get("lon", 0.0))
        if self._on_area_selected:
            self._on_area_selected(area)

    def _on_add(self) -> None:
        self._btn_add.setEnabled(False)
        self._add_form.clear()
        self._add_form.show()

    def _on_add_save(self, area: dict) -> None:
        areas = _load_areas()
        area[_ORIGIN_KEY] = "local"
        areas.append(area)
        _save_areas(areas)
        self._add_form.hide()
        self._btn_add.setEnabled(True)
        self._rebuild()

    def _on_add_cancel(self) -> None:
        self._add_form.hide()
        self._btn_add.setEnabled(True)

    def _on_delete(self, index: int) -> None:
        areas = _load_areas()
        if 0 <= index < len(areas):
            areas.pop(index)
            _save_areas(areas)
            self._rebuild()

