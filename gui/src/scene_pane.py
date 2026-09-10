"""
scene_pane.py — Scene Builder overlay pane.

Lets the user drag scene objects (people, events) onto the map,
move/reorder them, save named scenes, and show/hide/delete saved scenes.

Callbacks
---------
on_draft_changed(draft: list)    — draft objects changed; update tile_map
on_display_changed(objects: list)— visible saved-scene objects changed; update tile_map
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from PyQt5.QtCore import Qt, QMimeData, QPoint, QSize
from PyQt5.QtGui import QDrag, QImage, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

_SCENE_DIR  = Path(__file__).parent / "data" / "scene"
_SAVED_DIR  = _SCENE_DIR / "saved"
_RIBBON_W   = 48
_PANE_W     = 300

_THUMB_W    = 80   # thumbnail width in pane (px)
_THUMB_COLS = 3    # thumbnails per row

_DEFAULT_WIDTH_M = {
    "events":  20.0,   # ~car/incident footprint
    "people":  8.0,   # ~adult shoulder width
}

_TEXT = "#e8e8e8"
_DIM  = "#888888"

_PANE_STYLE = "QWidget#scenePane { background: rgba(20, 20, 30, 210); }"
_CARD_STYLE = "QFrame#sceneRow { background: rgba(40, 40, 55, 230); border-radius: 4px; }"

_SEC_STYLE = (
    "QLabel { color: #aaa; font-size: 10px; font-weight: bold;"
    " background: transparent; letter-spacing: 1px; }"
)
_ADD_STYLE = (
    "QPushButton { background: rgba(60,100,160,200); color: #ddd;"
    " border: none; border-radius: 4px; padding: 5px 8px; font-size: 11px; }"
    "QPushButton:hover { background: rgba(80,130,200,220); }"
)
_SAVE_STYLE = (
    "QPushButton { background: rgba(60,100,160,200); color: #ddd;"
    " border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; }"
    "QPushButton:hover { background: rgba(80,130,200,220); }"
    "QPushButton:disabled { background: rgba(40,60,100,120); color: #666; }"
)
_CLEAR_STYLE = (
    "QPushButton { background: rgba(50,50,65,200); color: #aaa;"
    " border: none; border-radius: 4px; padding: 4px 10px; font-size: 11px; }"
    "QPushButton:hover { background: rgba(70,70,90,220); color: #ccc; }"
)
_DELETE_STYLE = (
    "QPushButton { background: transparent; color: #555568;"
    " border: none; border-radius: 3px; padding: 2px 5px; font-size: 14px; }"
    "QPushButton:hover { color: rgba(80,130,200,230); background: rgba(36,58,110,60); }"
)
_TOGGLE_ON_STYLE = (
    "QPushButton { background: transparent; color: #5aaeee;"
    " border: none; padding: 2px 4px; font-size: 14px; }"
    "QPushButton:hover { color: #88ccff; }"
)
_TOGGLE_OFF_STYLE = (
    "QPushButton { background: transparent; color: #44445a;"
    " border: none; padding: 2px 4px; font-size: 14px; }"
    "QPushButton:hover { color: #7777aa; }"
)
_CONFIRM_STYLE = (
    "QWidget#confirmBar { background: rgba(22,28,45,220);"
    " border-top: 1px solid rgba(60,100,160,80); }"
    "QLabel { color: rgba(130,170,220,220); font-size: 11px; background: transparent; }"
)
_CONFIRM_YES_STYLE = (
    "QPushButton { background: rgba(36,60,110,220); color: rgba(130,180,240,230);"
    " border: 1px solid rgba(60,100,160,160); border-radius: 3px;"
    " padding: 2px 10px; font-size: 11px; }"
    "QPushButton:hover { background: rgba(46,80,140,230); }"
)
_CONFIRM_NO_STYLE = (
    "QPushButton { background: transparent; color: #777788;"
    " border: 1px solid #44445a; border-radius: 3px;"
    " padding: 2px 10px; font-size: 11px; }"
    "QPushButton:hover { color: #aaaacc; border-color: #666688; }"
)
_NAME_STYLE = (
    "QLineEdit { background: rgba(50,50,70,220); color: #ddd;"
    " border: 1px solid rgba(255,255,255,40); border-radius: 4px;"
    " padding: 3px 6px; font-size: 11px; }"
)
_THUMB_STYLE = (
    "QLabel { background: rgba(40,40,60,200); border: 1px solid rgba(255,255,255,20);"
    " border-radius: 3px; }"
    "QLabel:hover { border: 1px solid rgba(100,160,255,180); }"
)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_saved_scenes() -> list:
    """Return list of {name, path, objects} dicts for all saved scenes."""
    scenes = []
    if not _SAVED_DIR.exists():
        return scenes
    for p in sorted(_SAVED_DIR.glob("*.json")):
        try:
            with p.open(encoding="utf-8") as fh:
                data = json.load(fh)
            scenes.append({"name": data.get("name", p.stem),
                            "path": p,
                            "objects": data.get("objects", [])})
        except (OSError, json.JSONDecodeError):
            pass
    return scenes


def _save_scene(name: str, objects: list) -> Path:
    _SAVED_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip() or "scene"
    path = _SAVED_DIR / f"{safe}.json"
    # Avoid overwriting with a counter suffix
    counter = 1
    while path.exists():
        path = _SAVED_DIR / f"{safe}_{counter}.json"
        counter += 1
    with path.open("w", encoding="utf-8") as fh:
        json.dump({"name": name, "objects": objects}, fh, indent=2)
    return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_thumb(img_path: Path, width: int) -> QPixmap:
    """Load a PNG or SVG file and return a thumbnail QPixmap of the given width."""
    if img_path.suffix.lower() == ".svg":
        renderer = QSvgRenderer(str(img_path))
        if not renderer.isValid():
            return QPixmap()
        vb = renderer.viewBoxF()
        if vb.width() > 0:
            h = int(width * vb.height() / vb.width())
        else:
            h = width
        img = QImage(width, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        from PyQt5.QtGui import QPainter as _P
        painter = _P(img)
        renderer.render(painter)
        painter.end()
        return QPixmap.fromImage(img)
    else:
        px = QPixmap(str(img_path))
        if px.isNull():
            return px
        return px.scaledToWidth(width, Qt.SmoothTransformation)


# ---------------------------------------------------------------------------
# _DraggableThumbnail
# ---------------------------------------------------------------------------

class _DraggableThumbnail(QLabel):
    """Thumbnail label that starts a drag with the image relative path."""

    def __init__(self, rel_path: str, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self._rel_path = rel_path
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.width(), pixmap.height())
        self.setStyleSheet(_THUMB_STYLE)
        self.setToolTip(Path(rel_path).stem.replace("-", " ").replace("_", " ").title())
        self.setCursor(Qt.OpenHandCursor)
        self._drag_start = None

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag_start = ev.pos()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_start is None:
            return
        if (ev.pos() - self._drag_start).manhattanLength() < 6:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-scene-image", self._rel_path.encode())
        drag.setMimeData(mime)
        # Drag pixmap preview — hotspot centred on the preview image
        preview = self.pixmap().scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        drag.setPixmap(preview)
        drag.setHotSpot(QPoint(preview.width() // 2, preview.height() // 2))
        drag.exec_(Qt.CopyAction)
        self._drag_start = None

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_start = None


# ---------------------------------------------------------------------------
# _SceneRow — one saved-scene card
# ---------------------------------------------------------------------------

class _SceneRow(QFrame):
    def __init__(self, scene: dict, index: int, on_toggle, on_delete, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sceneRow")
        self.setStyleSheet(_CARD_STYLE)
        self._index  = index
        self._visible = scene.get("visible", True)

        name_lbl = QLabel(scene["name"])
        name_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: bold; background: transparent;"
        )
        n = len(scene.get("objects", []))
        detail_lbl = QLabel(f"{n} object{'s' if n != 1 else ''}")
        detail_lbl.setStyleSheet(f"color: {_DIM}; font-size: 9px; background: transparent;")

        left = QVBoxLayout()
        left.setContentsMargins(6, 4, 4, 4)
        left.setSpacing(2)
        left.addWidget(name_lbl)
        left.addWidget(detail_lbl)

        self._btn_toggle = QPushButton("\u25cf" if self._visible else "\u25cb")
        self._btn_toggle.setStyleSheet(_TOGGLE_ON_STYLE if self._visible else _TOGGLE_OFF_STYLE)
        self._btn_toggle.setFixedWidth(22)
        self._btn_toggle.setToolTip("Hide scene" if self._visible else "Show scene")
        self._btn_toggle.clicked.connect(lambda: on_toggle(self._index))

        self._btn_del = QPushButton("\u00d7")
        self._btn_del.setStyleSheet(_DELETE_STYLE)
        self._btn_del.setFixedWidth(24)
        self._btn_del.setToolTip("Delete scene")
        self._btn_del.clicked.connect(self._show_confirm)

        right = QHBoxLayout()
        right.setContentsMargins(4, 4, 6, 4)
        right.setSpacing(2)
        right.addWidget(self._btn_toggle)
        right.addWidget(self._btn_del)

        self._confirm_bar = QWidget(self)
        self._confirm_bar.setObjectName("confirmBar")
        self._confirm_bar.setStyleSheet(_CONFIRM_STYLE)
        btn_yes = QPushButton("Delete")
        btn_yes.setStyleSheet(_CONFIRM_YES_STYLE)
        btn_yes.clicked.connect(lambda: on_delete(self._index))
        btn_no = QPushButton("Cancel")
        btn_no.setStyleSheet(_CONFIRM_NO_STYLE)
        btn_no.clicked.connect(self._hide_confirm)
        cl = QHBoxLayout(self._confirm_bar)
        cl.setContentsMargins(8, 4, 6, 4)
        cl.setSpacing(6)
        cl.addWidget(QLabel("Confirm delete?"))
        cl.addStretch()
        cl.addWidget(btn_yes)
        cl.addWidget(btn_no)
        self._confirm_bar.hide()

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addLayout(left, stretch=1)
        row.addLayout(right)

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


# ---------------------------------------------------------------------------
# ScenePane
# ---------------------------------------------------------------------------

class ScenePane(QWidget):
    """
    Overlay pane for building and managing scenes.

    Callbacks
    ---------
    on_draft_changed(draft: list)    — draft object list changed
    on_display_changed(objects: list)— visible saved objects changed (merged list)
    """

    def __init__(self, on_draft_changed, on_display_changed, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scenePane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_PANE_STYLE)

        self._on_draft_changed   = on_draft_changed
        self._on_display_changed = on_display_changed

        self._draft: List[dict] = []
        self._saved: List[dict] = []   # {name, path, objects, visible}
        self._rows: list = []

        # Load existing scenes
        for s in _load_saved_scenes():
            s["visible"] = True
            self._saved.append(s)

        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        title = QLabel("Scene Builder")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold; background: transparent;"
        )

        # ── Palette ──────────────────────────────────────────────────────
        palette_widget = QWidget()
        palette_widget.setStyleSheet("background: transparent;")
        palette_layout = QVBoxLayout(palette_widget)
        palette_layout.setContentsMargins(0, 0, 0, 0)
        palette_layout.setSpacing(6)

        for category in ("events", "people"):
            cat_dir = _SCENE_DIR / category
            if not cat_dir.exists():
                continue
            images = sorted(
                p for p in cat_dir.iterdir()
                if p.suffix.lower() in (".png", ".svg")
            )
            if not images:
                continue

            sec_lbl = QLabel(category.upper())
            sec_lbl.setStyleSheet(_SEC_STYLE)
            palette_layout.addWidget(sec_lbl)

            grid = QWidget()
            grid.setStyleSheet("background: transparent;")
            grid_layout = QGridLayout(grid)
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setSpacing(4)

            col = 0
            for img_path in images:
                rel = f"{category}/{img_path.name}"
                thumb = _load_thumb(img_path, _THUMB_W)
                if thumb.isNull():
                    continue
                lbl = _DraggableThumbnail(rel, thumb, grid)
                grid_layout.addWidget(lbl, col // _THUMB_COLS, col % _THUMB_COLS)
                col += 1

            palette_layout.addWidget(grid)

        # ── Save draft controls ──────────────────────────────────────────
        save_widget = QWidget()
        save_widget.setStyleSheet("background: transparent;")
        save_layout = QVBoxLayout(save_widget)
        save_layout.setContentsMargins(0, 4, 0, 0)
        save_layout.setSpacing(4)

        draft_lbl = QLabel("Save current draft as scene:")
        draft_lbl.setStyleSheet(f"color: #aaa; font-size: 10px; background: transparent;")

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Scene name…")
        self._name_edit.setStyleSheet(_NAME_STYLE)
        self._name_edit.textChanged.connect(self._update_save_btn)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._btn_save = QPushButton("Save")
        self._btn_save.setStyleSheet(_SAVE_STYLE)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)

        btn_clear = QPushButton("Clear")
        btn_clear.setStyleSheet(_CLEAR_STYLE)
        btn_clear.clicked.connect(self._on_clear_draft)

        btn_row.addWidget(self._name_edit, stretch=1)
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(btn_clear)

        save_layout.addWidget(draft_lbl)
        save_layout.addLayout(btn_row)

        self._draft_count_lbl = QLabel("No objects placed yet.")
        self._draft_count_lbl.setStyleSheet(
            "color: #88b4e8; font-size: 10px; background: transparent;"
        )
        save_layout.addWidget(self._draft_count_lbl)

        # ── Saved scenes list ───────────────────────────────────────────
        scenes_lbl = QLabel("SAVED SCENES")
        scenes_lbl.setStyleSheet(_SEC_STYLE)

        self._row_container = QWidget()
        self._row_container.setStyleSheet("background: transparent;")
        self._row_layout = QVBoxLayout(self._row_container)
        self._row_layout.setContentsMargins(4, 0, 4, 0)
        self._row_layout.setSpacing(4)
        self._row_layout.addStretch(1)

        # ── Assemble scrollable content ─────────────────────────────────
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(8)
        cl.addWidget(title)
        cl.addWidget(self._make_divider())
        cl.addWidget(palette_widget)
        cl.addWidget(self._make_divider())
        cl.addWidget(save_widget)
        cl.addWidget(self._make_divider())
        cl.addWidget(scenes_lbl)
        cl.addWidget(self._row_container)
        cl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: rgba(255,255,255,15); width: 6px; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,50); border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addWidget(scroll)

        self._rebuild_scene_rows()

    @staticmethod
    def _make_divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet("color: rgba(255,255,255,40);")
        line.setFixedHeight(1)
        return line

    def _rebuild_scene_rows(self) -> None:
        for row in self._rows:
            self._row_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        for i, scene in enumerate(self._saved):
            row = _SceneRow(scene, i,
                            on_toggle=self._on_toggle_scene,
                            on_delete=self._on_delete_scene,
                            parent=self._row_container)
            self._row_layout.insertWidget(self._row_layout.count() - 1, row)
            self._rows.append(row)

    def _update_save_btn(self) -> None:
        self._btn_save.setEnabled(
            bool(self._name_edit.text().strip()) and len(self._draft) > 0
        )

    # ------------------------------------------------------------------ #
    # Draft management                                                     #
    # ------------------------------------------------------------------ #

    def on_object_dropped(self, rel_path: str, lat: float, lon: float) -> None:
        """Called when user drops a palette image onto the map."""
        category = rel_path.split("/")[0]
        width_m  = _DEFAULT_WIDTH_M.get(category, 8.0)
        z_order  = max((o["z_order"] for o in self._draft), default=-1) + 1
        self._draft.append({
            "image":   rel_path,
            "lat":     lat,
            "lon":     lon,
            "width_m": width_m,
            "z_order": z_order,
        })
        self._fire_draft_changed()

    def on_object_moved(self, idx: int, lat: float, lon: float) -> None:
        if 0 <= idx < len(self._draft):
            self._draft[idx]["lat"] = lat
            self._draft[idx]["lon"] = lon
            self._fire_draft_changed()

    def on_object_clicked(self, idx: int) -> None:
        """Bring object to front."""
        if 0 <= idx < len(self._draft):
            max_z = max(o["z_order"] for o in self._draft)
            self._draft[idx]["z_order"] = max_z + 1
            self._fire_draft_changed()

    def on_object_right_clicked(self, idx: int) -> None:
        """Send object to back."""
        if 0 <= idx < len(self._draft):
            min_z = min(o["z_order"] for o in self._draft)
            self._draft[idx]["z_order"] = min_z - 1
            self._fire_draft_changed()

    def _fire_draft_changed(self) -> None:
        n = len(self._draft)
        self._draft_count_lbl.setText(
            f"{n} object{'s' if n != 1 else ''} in draft." if n else "No objects placed yet."
        )
        self._update_save_btn()
        self._on_draft_changed(list(self._draft))

    def _on_clear_draft(self) -> None:
        self._draft.clear()
        self._fire_draft_changed()

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        if not name or not self._draft:
            return
        path = _save_scene(name, list(self._draft))
        self._saved.append({"name": name, "path": path,
                             "objects": list(self._draft), "visible": True})
        self._draft.clear()
        self._name_edit.clear()
        self._fire_draft_changed()
        self._rebuild_scene_rows()
        self._push_display_changed()

    # ------------------------------------------------------------------ #
    # Saved scene management                                               #
    # ------------------------------------------------------------------ #

    def _on_toggle_scene(self, index: int) -> None:
        if 0 <= index < len(self._saved):
            self._saved[index]["visible"] = not self._saved[index]["visible"]
            self._rebuild_scene_rows()
            self._push_display_changed()

    def _on_delete_scene(self, index: int) -> None:
        if 0 <= index < len(self._saved):
            try:
                self._saved[index]["path"].unlink(missing_ok=True)
            except OSError:
                pass
            self._saved.pop(index)
            self._rebuild_scene_rows()
            self._push_display_changed()

    def _push_display_changed(self) -> None:
        merged = []
        for s in self._saved:
            if s.get("visible", True):
                merged.extend(s["objects"])
        self._on_display_changed(merged)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def reposition(self) -> None:
        p = self.parent()
        self.setGeometry(_RIBBON_W, 0, _PANE_W, p.height())
        self.raise_()
