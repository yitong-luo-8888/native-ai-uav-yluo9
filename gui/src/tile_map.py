"""
tile_map.py — Slippy-map widget backed by ESRI World Imagery tiles.

Fetch order: memory LRU cache → disk cache → network.
Disk cache lives at ~/.cache/dronemap/tiles/{z}/{x}/{y}

Pan  : left-drag
Zoom : scroll wheel

lat_lon_to_screen() converts a lat/lon to widget-pixel coordinates so
that drone icons can be drawn on top by a caller.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Set, Tuple

import requests

from PyQt5.QtCore import Qt, pyqtSignal, QPoint, QPointF, QTimer
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygon, QPolygonF, QFont
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QWidget

# Satellite tile providers — each has its own URL template and disk-cache folder.
# ESRI puts y before x in the path (non-standard TMS order).
TILE_PROVIDERS = {
    "standard": {
        "label": "Standard (cloud-composited)",
        "url":   ("https://server.arcgisonline.com/ArcGIS/rest/services"
                  "/World_Imagery/MapServer/tile/{z}/{y}/{x}"),
        "cache": Path.home() / ".cache" / "dronemap" / "tiles" / "standard",
    },
    "clarity": {
        "label": "Clarity (sharper, orthographic)",
        "url":   ("https://clarity.maptiles.arcgis.com/arcgis/rest/services"
                  "/World_Imagery/MapServer/tile/{z}/{y}/{x}"),
        "cache": Path.home() / ".cache" / "dronemap" / "tiles" / "clarity",
    },
}
_DEFAULT_PROVIDER = "clarity"

# Optional Esri API key/token, for higher-rate-limit authenticated access.
# Unset (the default) falls back to the same unauthenticated requests this
# always made — set the env var to opt in, no code change needed either way.
_ESRI_API_KEY = os.environ.get("ESRI_API_KEY")

_TILE_SIZE  = 256         # ESRI serves 256 × 256 px tiles
_CACHE_MAX  = 512         # max tiles held in memory (LRU eviction)
_ZOOM_MIN   = 1
_ZOOM_MAX   = 20
_MAX_FETCH  = threading.Semaphore(8)   # cap concurrent HTTP requests
_ERROR_RETRY_COOLDOWN_S = 5.0   # after a 404/error, hold off re-requesting that tile

_HEADING_ANIM_MS  = 16     # timer interval (~60 fps)
_HEADING_ANIM_DUR = 0.40   # total rotation duration in seconds

_SCENE_MIN_PX = 4    # minimum screen width (px) — just prevents zero-size, not a visibility floor

# Drone arrow polygon — points north (up), centred on origin.
# Rotated at draw time by the drone's heading.
_ARROW = QPolygon([
    QPoint(  0, -18),   # tip
    QPoint( 12,  10),   # right wing
    QPoint(  0,   2),   # centre notch
    QPoint(-12,  10),   # left wing
])


# ---------------------------------------------------------------------------
# Web Mercator helpers
# ---------------------------------------------------------------------------

def _ll_to_tile(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Lat/lon → fractional tile coordinates at zoom."""
    n  = 2.0 ** zoom
    tx = (lon + 180.0) / 360.0 * n
    lr = math.radians(lat)
    ty = (1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * n
    return tx, ty


def _tile_to_ll(tx: float, ty: float, zoom: int) -> Tuple[float, float]:
    """Fractional tile coordinates → lat/lon."""
    n   = 2.0 ** zoom
    lon = tx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ty / n))))
    return lat, lon


# ---------------------------------------------------------------------------
# TileMap widget
# ---------------------------------------------------------------------------

class TileMap(QWidget):
    """
    Displays an ESRI World Imagery slippy map.

    Tiles are served from memory cache, then disk cache, then the ESRI
    network endpoint.  No API key required.

    The widget owns tile fetching, caching, pan and zoom.
    Call lat_lon_to_screen() to get pixel positions for overlay drawing.
    """

    _tile_ready = pyqtSignal(int, int, int, bytes)  # z, x, y, image bytes
    _tile_error = pyqtSignal(int, int, int, str)     # z, x, y, message
    _tile_404   = pyqtSignal(int, int, int)          # z, x, y — tile source has no data at this coordinate

    scene_drop_requested    = pyqtSignal(str, float, float)     # rel_path, lat, lon
    scene_object_moved      = pyqtSignal(int, float, float)     # idx, lat, lon
    scene_object_clicked    = pyqtSignal(int)                   # idx → bring to front
    scene_object_right_clicked = pyqtSignal(int)                # idx → send to back

    # Emitted after a pan or zoom so overlays can reposition themselves
    view_changed = pyqtSignal()

    # Emitted when the two-click heading pick advances or completes
    heading_pick_step_changed = pyqtSignal(int)                 # 1 = position set, awaiting direction
    heading_arrow_shown       = pyqtSignal()                    # arrow placed, awaiting confirmation
    heading_pick_complete     = pyqtSignal(int)                 # bearing in degrees (on accept)

    def __init__(
        self,
        lat: float,
        lon: float,
        zoom: int = 13,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._lat  = lat
        self._lon  = lon
        self._zoom = zoom

        self._provider: str = _DEFAULT_PROVIDER
        self._cache:   OrderedDict[Tuple[int, int, int], QPixmap] = OrderedDict()
        self._pending: Set[Tuple[int, int, int]] = set()
        # Tiles that just 404'd or errored — held back from re-request until this
        # deadline (monotonic time) passes, so a burst of failures (e.g. a rate
        # limit trip from the camera's fresh-mosaic requests) doesn't turn into an
        # immediate retry storm against the same tiles every capture tick.
        self._retry_after: dict = {}
        # Learned ceiling: lowered whenever a tile 404s at some zoom, since the
        # provider has no imagery there. Session-wide, not per-location.
        self._max_known_zoom: int = _ZOOM_MAX

        self._drag_start: Optional[QPoint] = None
        self._drag_dx: int = 0
        self._drag_dy: int = 0

        self._drones = []

        self._scene_mode:   bool = False
        self._scene_draft:  list = []     # interactive draft objects
        self._scene_saved:  list = []     # display-only saved scene objects
        self._scene_img_cache: dict = {}         # rel_path → base QPixmap
        self._scene_scaled_cache: dict = {}     # (rel_path, pw, ph) → scaled QPixmap
        self._scene_drag_idx = None       # type: Optional[int]
        self._scene_click_origin = None   # type: Optional[QPoint]

        self.setMouseTracking(True)   # needed for cursor-change on hover without button held

        self._map_heading:        float = 0.0   # current displayed heading (animated)
        self._heading_target:     float = 0.0   # final heading after animation
        self._heading_anim_start: float = 0.0   # heading at animation start
        self._heading_anim_t0:    float = 0.0   # monotonic time at start
        self._heading_pick_mode:     bool                           = False
        self._heading_pick_origin:   Optional[Tuple[float, float]] = None
        self._heading_arrow_mode:    bool                           = False
        self._heading_arrow_origin:  Optional[Tuple[float, float]] = None
        self._heading_arrow_target:  Optional[Tuple[float, float]] = None
        self._heading_arrow_dragging: bool                          = False

        self._flash_on = True
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._on_flash_tick)
        self._flash_timer.start(500)

        self._heading_anim_timer = QTimer(self)
        self._heading_anim_timer.setInterval(_HEADING_ANIM_MS)
        self._heading_anim_timer.timeout.connect(self._on_heading_anim_tick)

        self.setCursor(Qt.OpenHandCursor)
        self.setAcceptDrops(True)

        self._tile_ready.connect(self._on_tile_ready)
        self._tile_error.connect(self._on_tile_error)
        self._tile_404.connect(self._on_tile_404)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_drones(self, drones) -> None:
        """Update the drone list and repaint."""
        self._drones = drones
        self.update()

    def set_scene_mode(self, active: bool) -> None:
        """Enable/disable scene object interaction."""
        self._scene_mode = active
        self._scene_drag_idx = None
        self._scene_click_origin = None

    def set_scene_draft(self, objects: list) -> None:
        self._scene_draft = list(objects)
        self.update()

    def set_scene_saved(self, objects: list) -> None:
        self._scene_saved = list(objects)
        self.update()

    def _get_scene_image(self, rel_path: str) -> QPixmap:
        """Return a base QPixmap for the given relative scene image path.

        SVG files are rendered to a 512-px-wide QPixmap once and cached.
        PNG files are loaded once and cached. Scaling to screen size is done
        at draw time and cached separately in _scene_scaled_cache.
        """
        if rel_path not in self._scene_img_cache:
            full = Path(__file__).parent / "data" / "scene" / rel_path
            if full.suffix.lower() == ".svg":
                renderer = QSvgRenderer(str(full))
                if renderer.isValid():
                    vb = renderer.viewBoxF()
                    base_w = 512
                    base_h = int(base_w * vb.height() / vb.width()) if vb.width() > 0 else base_w
                    img = QImage(base_w, base_h, QImage.Format_ARGB32_Premultiplied)
                    img.fill(0)
                    painter = QPainter(img)
                    renderer.render(painter)
                    painter.end()
                    px = QPixmap.fromImage(img)
                else:
                    px = QPixmap()
            else:
                px = QPixmap(str(full))
            self._scene_img_cache[rel_path] = px
        return self._scene_img_cache[rel_path]

    def _get_scene_scaled(self, rel_path: str, pw: int, ph: int) -> QPixmap:
        """Return a scaled QPixmap, cached by (rel_path, pw, ph) to avoid per-frame rescaling."""
        key = (rel_path, pw, ph)
        if key not in self._scene_scaled_cache:
            base = self._get_scene_image(rel_path)
            if base.isNull():
                self._scene_scaled_cache[key] = base
            else:
                self._scene_scaled_cache[key] = base.scaled(
                    pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
        return self._scene_scaled_cache[key]

    def _obj_screen_rect(self, obj: dict):
        """Return (cx, cy, pw, ph) screen coords for a scene object, or None."""
        sx, sy = self.lat_lon_to_screen(obj["lat"], obj["lon"])
        mpp = (math.cos(math.radians(obj["lat"])) * 2 * math.pi * 6378137) / (256 * 2 ** self._zoom)
        pw = max(obj["width_m"] / mpp, _SCENE_MIN_PX)
        img = self._get_scene_image(obj["image"])
        if img.isNull() or img.width() == 0:
            return None
        ph = pw * img.height() / img.width()
        return sx, sy, pw, ph

    def _hit_test_scene_draft(self, x: int, y: int) -> Optional[int]:
        """Return draft index of topmost object under (x,y), or None."""
        # Check in reverse z-order (topmost first)
        sorted_objs = sorted(enumerate(self._scene_draft),
                             key=lambda t: t[1].get("z_order", 0), reverse=True)
        for idx, obj in sorted_objs:
            r = self._obj_screen_rect(obj)
            if r is None:
                continue
            cx, cy, pw, ph = r
            if abs(x - cx) <= pw / 2 and abs(y - cy) <= ph / 2:
                return idx
        return None

    def set_center(self, lat: float, lon: float, zoom: Optional[int] = None) -> None:
        """Reposition the map centre and optionally change zoom."""
        self._lat = lat
        self._lon = lon
        if zoom is not None:
            self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, zoom))
            self._scene_scaled_cache.clear()
        self.update()

    def set_map_heading(self, degrees: int) -> None:
        """Smoothly rotate the map so that *degrees* faces the top of the screen."""
        target = float(degrees % 360)
        # Shortest angular path
        delta = (target - self._map_heading + 180.0) % 360.0 - 180.0
        if abs(delta) < 0.5:
            return
        self._heading_target     = target
        self._heading_anim_start = self._map_heading
        self._heading_anim_t0    = time.monotonic()
        self._heading_anim_timer.start()   # restarts if already running

    def _on_heading_anim_tick(self) -> None:
        elapsed = time.monotonic() - self._heading_anim_t0
        t = min(elapsed / _HEADING_ANIM_DUR, 1.0)
        # Smoothstep easing: slow at start and end, fast in the middle
        t_e = t * t * (3.0 - 2.0 * t)
        # Shortest path from start to target
        delta = (self._heading_target - self._heading_anim_start + 180.0) % 360.0 - 180.0
        self._map_heading = (self._heading_anim_start + t_e * delta) % 360.0
        self.update()
        if t >= 1.0:
            self._heading_anim_timer.stop()
            self._map_heading = self._heading_target

    def set_heading_pick_mode(self, active: bool) -> None:
        """Enter/exit two-click heading-pick mode (also cancels any pending arrow)."""
        self._heading_pick_mode      = active
        self._heading_pick_origin    = None
        self._heading_arrow_mode     = False
        self._heading_arrow_origin   = None
        self._heading_arrow_target   = None
        self._heading_arrow_dragging = False
        self.setCursor(Qt.CrossCursor if active else Qt.OpenHandCursor)
        self.update()

    def accept_heading_arrow(self) -> None:
        """Accept the pending heading arrow and apply the computed bearing."""
        if not self._heading_arrow_mode:
            return
        lat1, lon1 = self._heading_arrow_origin
        lat2, lon2 = self._heading_arrow_target
        bearing = self._bearing(lat1, lon1, lat2, lon2)
        self._heading_arrow_mode     = False
        self._heading_arrow_origin   = None
        self._heading_arrow_target   = None
        self._heading_arrow_dragging = False
        self.setCursor(Qt.OpenHandCursor)
        self.heading_pick_complete.emit(bearing)
        self.update()

    @staticmethod
    def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
        """Return the compass bearing (0-359°) from point 1 to point 2."""
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlon = lon2 - lon1
        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return int((math.degrees(math.atan2(x, y)) + 360) % 360)

    def lat_lon_to_screen(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Convert a lat/lon to pixel (x, y) in the painter's (map-space) coordinate system.
        These coordinates are used directly with QPainter, which applies the map rotation
        transform, so they will appear at the correct rotated position on screen.
        """
        ctx, cty = _ll_to_tile(self._lat, self._lon, self._zoom)
        tx,  ty  = _ll_to_tile(lat,       lon,       self._zoom)
        cx = self.width()  / 2 + self._drag_dx
        cy = self.height() / 2 + self._drag_dy
        return cx + (tx - ctx) * _TILE_SIZE, cy + (ty - cty) * _TILE_SIZE

    def _screen_to_lat_lon(self, screen_x: float, screen_y: float) -> Tuple[float, float]:
        """
        Convert a screen pixel coordinate (as received from Qt mouse/drop events)
        to (lat, lon). Inverse of lat_lon_to_screen(), including the map-rotation
        correction since Qt events arrive in screen space, not painter/map space.
        """
        mx, my = self._screen_to_map_space(screen_x, screen_y)
        ctx, cty = _ll_to_tile(self._lat, self._lon, self._zoom)
        cx = self.width()  / 2 + self._drag_dx
        cy = self.height() / 2 + self._drag_dy
        tx = ctx + (mx - cx) / _TILE_SIZE
        ty = cty + (my - cy) / _TILE_SIZE
        return _tile_to_ll(tx, ty, self._zoom)

    # ------------------------------------------------------------------ #
    # Qt events                                                            #
    # ------------------------------------------------------------------ #

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        W, H = self.width(), self.height()

        # Apply map rotation around the widget centre so the operator's
        # facing direction appears at the top of the screen.
        if self._map_heading != 0.0:
            p.translate(W / 2, H / 2)
            p.rotate(-self._map_heading)
            p.translate(-W / 2, -H / 2)

        # Pixel position of the map centre inside the widget
        cx = W / 2 + self._drag_dx
        cy = H / 2 + self._drag_dy

        # Fractional tile coords of the map centre
        ctx, cty = _ll_to_tile(self._lat, self._lon, self._zoom)

        n_tiles = 2 ** self._zoom

        # Single integer origin: pixel position of tile (0, 0)'s top-left.
        # All tile positions are exact integer multiples of _TILE_SIZE from
        # here, guaranteeing zero gaps between tiles.
        origin_x = int(cx - ctx * _TILE_SIZE)
        origin_y = int(cy - cty * _TILE_SIZE)

        # Tile index range covering the widget (1-tile padding for safety).
        # When rotated, the screen diagonal is larger than either side, so
        # expand the fetch range to avoid grey corners.
        extra = 0
        if self._map_heading != 0.0:
            diag = math.sqrt(W * W + H * H)
            extra = int(math.ceil((diag - min(W, H)) / (2 * _TILE_SIZE))) + 1
        left  = int(math.floor(-origin_x / _TILE_SIZE)) - 1 - extra
        top   = int(math.floor(-origin_y / _TILE_SIZE)) - 1 - extra
        right = int(math.ceil((W - origin_x) / _TILE_SIZE)) + extra
        bot   = int(math.ceil((H - origin_y) / _TILE_SIZE)) + extra

        for tx in range(left, right + 1):
            for ty in range(top, bot + 1):
                px = origin_x + tx * _TILE_SIZE
                py = origin_y + ty * _TILE_SIZE

                # Wrap x around the globe; clamp y to valid range
                tx_w = tx % n_tiles
                if tx_w < 0:
                    tx_w += n_tiles
                ty_c = max(0, min(n_tiles - 1, ty))

                key = (self._zoom, tx_w, ty_c)
                pix = self._cache.get(key)
                if pix is not None:
                    self._cache.move_to_end(key)
                    p.drawPixmap(px, py, _TILE_SIZE, _TILE_SIZE, pix)
                else:
                    p.fillRect(px, py, _TILE_SIZE, _TILE_SIZE, QColor(0x50, 0x50, 0x50))
                    self._request_tile(self._zoom, tx_w, ty_c)

        self._draw_scene(p)

        # Drones always on top of all map overlays
        self._draw_drone_arrows(p)

        # Heading alignment arrow (step 2 placed, awaiting confirmation)
        if self._heading_arrow_mode:
            self._draw_heading_arrow(p)

        # Origin dot for step 1 of heading pick (position set, awaiting direction click)
        if self._heading_pick_origin is not None:
            sx, sy = self.lat_lon_to_screen(*self._heading_pick_origin)
            p.setPen(QPen(QColor(60, 160, 255, 255), 2))
            p.setBrush(QColor(60, 160, 255, 180))
            p.drawEllipse(int(sx) - 8, int(sy) - 8, 16, 16)
            p.setPen(QPen(QColor(255, 255, 255, 220), 1))
            p.setBrush(QColor(255, 255, 255, 220))
            p.drawEllipse(int(sx) - 3, int(sy) - 3, 6, 6)

        self._draw_compass(p)

        p.end()

    def mousePressEvent(self, ev) -> None:
        if self._heading_pick_mode:
            if ev.button() == Qt.LeftButton:
                lat, lon = self._screen_to_lat_lon(ev.x(), ev.y())
                if self._heading_pick_origin is None:
                    self._heading_pick_origin = (lat, lon)
                    self.heading_pick_step_changed.emit(1)
                    self.update()
                else:
                    self._heading_arrow_origin   = self._heading_pick_origin
                    self._heading_arrow_target   = (lat, lon)
                    self._heading_pick_mode      = False
                    self._heading_pick_origin    = None
                    self._heading_arrow_mode     = True
                    self._heading_arrow_dragging = True
                    self.setCursor(Qt.ClosedHandCursor)
                    self.heading_arrow_shown.emit()
                    self.update()
            return

        if self._heading_arrow_mode:
            if ev.button() == Qt.LeftButton and self._hit_test_arrowhead(ev.x(), ev.y()):
                self._heading_arrow_dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            return  # no map pan while arrow is pending

        if self._scene_mode:
            if ev.button() == Qt.LeftButton:
                hit = self._hit_test_scene_draft(ev.x(), ev.y())
                if hit is not None:
                    self._scene_drag_idx = hit
                    self._scene_click_origin = ev.pos()
                    self.setCursor(Qt.ClosedHandCursor)
                # else: allow normal map pan (fall through below)
                return
            elif ev.button() == Qt.RightButton:
                hit = self._hit_test_scene_draft(ev.x(), ev.y())
                if hit is not None:
                    self.scene_object_right_clicked.emit(hit)
                    return
            return

        if ev.button() == Qt.LeftButton:
            self._drag_start = ev.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseDoubleClickEvent(self, ev) -> None:
        if self._heading_arrow_mode:
            if ev.button() == Qt.LeftButton and self._hit_test_arrowhead(ev.x(), ev.y()):
                self.accept_heading_arrow()
            return

    def mouseMoveEvent(self, ev) -> None:
        if self._heading_arrow_mode:
            if self._heading_arrow_dragging and (ev.buttons() & Qt.LeftButton):
                lat, lon = self._screen_to_lat_lon(ev.x(), ev.y())
                self._heading_arrow_target = (lat, lon)
                self.update()
            elif self._hit_test_arrowhead(ev.x(), ev.y()):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
            return

        if self._scene_mode:
            if self._scene_drag_idx is not None and (ev.buttons() & Qt.LeftButton):
                lat, lon = self._screen_to_lat_lon(ev.x(), ev.y())
                draft = list(self._scene_draft)
                draft[self._scene_drag_idx] = {**draft[self._scene_drag_idx],
                                               "lat": lat, "lon": lon}
                self._scene_draft = draft
                self.update()
            return

        if self._drag_start is not None:
            d = ev.pos() - self._drag_start
            dx, dy = float(d.x()), float(d.y())
            if self._map_heading != 0.0:
                # Drag delta is in screen space; convert to map (painter) space.
                rad = math.radians(self._map_heading)
                cos_a, sin_a = math.cos(rad), math.sin(rad)
                self._drag_dx = dx * cos_a - dy * sin_a
                self._drag_dy = dx * sin_a + dy * cos_a
            else:
                self._drag_dx = dx
                self._drag_dy = dy
            self.update()
            self.view_changed.emit()

    def mouseReleaseEvent(self, ev) -> None:
        if self._heading_arrow_mode:
            if ev.button() == Qt.LeftButton and self._heading_arrow_dragging:
                self._heading_arrow_dragging = False
                self.setCursor(Qt.OpenHandCursor)
            return

        if self._scene_mode:
            if ev.button() == Qt.LeftButton:
                if self._scene_drag_idx is not None:
                    origin = self._scene_click_origin
                    moved = origin is not None and (ev.pos() - origin).manhattanLength() > 5
                    lat, lon = self._screen_to_lat_lon(ev.x(), ev.y())
                    idx = self._scene_drag_idx
                    self._scene_drag_idx = None
                    self._scene_click_origin = None
                    self.setCursor(Qt.ArrowCursor)
                    if moved:
                        self.scene_object_moved.emit(idx, lat, lon)
                    else:
                        self.scene_object_clicked.emit(idx)
            return

        if ev.button() == Qt.LeftButton and self._drag_start is not None:
            ctx, cty = _ll_to_tile(self._lat, self._lon, self._zoom)
            self._lat, self._lon = _tile_to_ll(
                ctx - self._drag_dx / _TILE_SIZE,
                cty - self._drag_dy / _TILE_SIZE,
                self._zoom,
            )
            self._drag_dx = 0
            self._drag_dy = 0
            self._drag_start = None
            self.setCursor(Qt.OpenHandCursor)
            self.update()
            self.view_changed.emit()

    def wheelEvent(self, ev) -> None:
        if ev.angleDelta().y() > 0:
            self._zoom = min(self._zoom + 1, _ZOOM_MAX)
        else:
            self._zoom = max(self._zoom - 1, _ZOOM_MIN)
        self._scene_scaled_cache.clear()
        self.update()
        self.view_changed.emit()

    # ------------------------------------------------------------------ #
    # Drag-and-drop — scene image placement                               #
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasFormat("application/x-scene-image"):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:
        if ev.mimeData().hasFormat("application/x-scene-image"):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev) -> None:
        if ev.mimeData().hasFormat("application/x-scene-image"):
            rel_path = ev.mimeData().data("application/x-scene-image").data().decode()
            lat, lon = self._screen_to_lat_lon(ev.pos().x(), ev.pos().y())
            self.scene_drop_requested.emit(rel_path, lat, lon)
            ev.acceptProposedAction()
            return
        ev.ignore()

    # ------------------------------------------------------------------ #
    # Heading arrow (pending confirmation)                                #
    # ------------------------------------------------------------------ #

    def _screen_to_map_space(self, sx: float, sy: float) -> Tuple[float, float]:
        """Convert screen pixel coords to painter/map-space pixel coords."""
        if self._map_heading != 0.0:
            hw, hh = self.width() / 2, self.height() / 2
            rad = math.radians(self._map_heading)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            dx, dy = sx - hw, sy - hh
            return hw + dx * cos_a - dy * sin_a, hh + dx * sin_a + dy * cos_a
        return float(sx), float(sy)

    def _map_to_screen(self, mx: float, my: float) -> Tuple[float, float]:
        """Convert painter/map-space pixel coords to screen pixel coords."""
        if self._map_heading != 0.0:
            hw, hh = self.width() / 2, self.height() / 2
            rad = math.radians(self._map_heading)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            dx, dy = mx - hw, my - hh
            return hw + dx * cos_a + dy * sin_a, hh - dx * sin_a + dy * cos_a
        return float(mx), float(my)

    def _hit_test_arrowhead(self, screen_x: float, screen_y: float) -> bool:
        if not self._heading_arrow_mode or self._heading_arrow_target is None:
            return False
        tx, ty = self.lat_lon_to_screen(*self._heading_arrow_target)
        mx, my = self._screen_to_map_space(screen_x, screen_y)
        return math.hypot(mx - tx, my - ty) <= 16

    def _draw_heading_arrow(self, p: QPainter) -> None:
        """Draw the draggable heading alignment arrow."""
        ox, oy = self.lat_lon_to_screen(*self._heading_arrow_origin)
        tx, ty = self.lat_lon_to_screen(*self._heading_arrow_target)
        dx, dy = tx - ox, ty - oy
        length = math.hypot(dx, dy)
        if length < 2:
            return

        ux, uy   = dx / length, dy / length   # unit direction
        perp_x   = -uy                         # perpendicular (left)
        perp_y   =  ux

        HEAD, HALF = 18, 8    # arrowhead depth, half-width (pixels)
        base_cx = tx - ux * HEAD
        base_cy = ty - uy * HEAD
        tip    = QPointF(tx, ty)
        base_l = QPointF(base_cx - perp_x * HALF, base_cy - perp_y * HALF)
        base_r = QPointF(base_cx + perp_x * HALF, base_cy + perp_y * HALF)

        p.setRenderHint(QPainter.Antialiasing)

        # Shadow line
        p.setPen(QPen(QColor(0, 0, 0, 130), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(ox, oy), QPointF(base_cx, base_cy))

        # White shaft
        p.setPen(QPen(QColor(255, 255, 255, 220), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(ox, oy), QPointF(base_cx, base_cy))

        # Arrowhead shadow
        p.setPen(QPen(QColor(0, 0, 0, 100), 2))
        p.setBrush(QColor(0, 0, 0, 100))
        shadow_tip    = QPointF(tx + 2,        ty + 2)
        shadow_base_l = QPointF(base_l.x() + 2, base_l.y() + 2)
        shadow_base_r = QPointF(base_r.x() + 2, base_r.y() + 2)
        p.drawPolygon(QPolygonF([shadow_tip, shadow_base_l, shadow_base_r]))

        # Arrowhead
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawPolygon(QPolygonF([tip, base_l, base_r]))

        # Origin dot
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawEllipse(QPointF(ox, oy), 6, 6)

        # Bearing label — always upright, offset perpendicular to the shaft
        bearing = self._bearing(*self._heading_arrow_origin, *self._heading_arrow_target)
        label = f"{bearing}°"
        font = QFont()
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        # Compute label centre in map space, then project to screen space for upright drawing
        lsx, lsy = self._map_to_screen(tx + perp_x * 18, ty + perp_y * 18)
        lx = int(lsx - fm.horizontalAdvance(label) / 2)
        ly = int(lsy + fm.ascent() / 2)
        p.save()
        p.resetTransform()
        p.setPen(QPen(QColor(0, 0, 0, 180), 3))
        p.drawText(lx + 1, ly + 1, label)
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(lx, ly, label)
        p.restore()

    # ------------------------------------------------------------------ #
    # Compass rose                                                        #
    # ------------------------------------------------------------------ #

    def _draw_compass(self, p: QPainter) -> None:
        """Draw an N/S/E/W compass rose in the top-right corner, oriented to the map heading."""
        W = self.width()
        MARGIN = 14
        R      = 26          # background circle radius
        ARM    = R - 5       # length of each arm from centre
        LABEL  = R + 9       # distance from centre to label

        cx = W - MARGIN - R
        cy = MARGIN + R

        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.Antialiasing)

        # Background disc
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 100))
        p.drawEllipse(int(cx - R), int(cy - R), R * 2, R * 2)

        # Thin outer ring
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawEllipse(int(cx - R), int(cy - R), R * 2, R * 2)

        # Direction unit vectors in screen space for a map rotated by _map_heading:
        #   North → (-sin h, -cos h),  South → (sin h,  cos h)
        #   East  → ( cos h, -sin h),  West  → (-cos h, sin h)
        h      = math.radians(self._map_heading)
        cos_h  = math.cos(h)
        sin_h  = math.sin(h)
        dirs   = {
            "N": (-sin_h, -cos_h),
            "S": ( sin_h,  cos_h),
            "E": ( cos_h, -sin_h),
            "W": (-cos_h,  sin_h),
        }

        # S / E / W arms — thin white lines with small dot at tip
        p.setPen(QPen(QColor(255, 255, 255, 160), 1.5))
        for name in ("S", "E", "W"):
            dx, dy = dirs[name]
            p.drawLine(
                QPointF(cx + dx * 5,   cy + dy * 5),
                QPointF(cx + dx * ARM, cy + dy * ARM),
            )
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 160))
        for name in ("S", "E", "W"):
            dx, dy = dirs[name]
            p.drawEllipse(QPointF(cx + dx * ARM, cy + dy * ARM), 2.5, 2.5)

        # N arrow — filled white triangle
        ndx, ndy = dirs["N"]
        perp_x, perp_y = -ndy, ndx          # 90° CCW of N direction
        half_base = 5
        tip    = QPointF(cx + ndx * ARM,          cy + ndy * ARM)
        base_l = QPointF(cx + ndx * 5 - perp_x * half_base,
                         cy + ndy * 5 - perp_y * half_base)
        base_r = QPointF(cx + ndx * 5 + perp_x * half_base,
                         cy + ndy * 5 + perp_y * half_base)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawPolygon(QPolygonF([tip, base_l, base_r]))

        # Labels — drawn upright in screen space at the tip of each arm
        font = QFont()
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        for name, (dx, dy) in dirs.items():
            alpha = 240 if name == "N" else 180
            p.setPen(QColor(255, 255, 255, alpha))
            lx = cx + dx * LABEL
            ly = cy + dy * LABEL
            tw = fm.horizontalAdvance(name)
            th = fm.ascent()
            p.drawText(int(lx - tw / 2), int(ly + th / 2), name)

        p.restore()

    # ------------------------------------------------------------------ #
    # Drone arrows                                                        #
    # ------------------------------------------------------------------ #

    def _is_flashing(self, d) -> bool:
        pilot = (d.onboard_pilot or "").lower()
        return pilot in ("takeoff", "land")

    def _draw_scene(self, p: QPainter) -> None:
        """Draw scene objects: saved (display-only) then draft (interactive) by z_order."""
        all_layers = [
            (self._scene_saved, False),
            (self._scene_draft, True),
        ]
        for objects, is_draft in all_layers:
            if not objects:
                continue
            for obj in sorted(objects, key=lambda o: o.get("z_order", 0)):
                r = self._obj_screen_rect(obj)
                if r is None:
                    continue
                cx, cy, pw, ph = r
                # Skip if completely off-screen
                W, H = self.width(), self.height()
                if cx + pw / 2 < 0 or cx - pw / 2 > W:
                    continue
                if cy + ph / 2 < 0 or cy - ph / 2 > H:
                    continue
                scaled = self._get_scene_scaled(obj["image"], int(pw), int(ph))
                if scaled.isNull():
                    continue
                p.drawPixmap(int(cx - scaled.width() / 2),
                             int(cy - scaled.height() / 2),
                             scaled)
                # Drag highlight
                if is_draft and self._scene_drag_idx is not None:
                    idx = self._scene_drag_idx
                    if self._scene_draft.index(obj) == idx:
                        p.save()
                        p.setPen(QPen(QColor(100, 180, 255, 200), 2))
                        p.setBrush(Qt.NoBrush)
                        p.drawRect(int(cx - pw / 2), int(cy - ph / 2), int(pw), int(ph))
                        p.restore()

    def _draw_drone_arrows(self, p: QPainter) -> None:
        if not self._drones:
            return

        W, H = self.width(), self.height()

        white_pen = QPen(QColor("white"))
        white_pen.setWidth(1)
        white_pen.setJoinStyle(Qt.MiterJoin)

        p.setRenderHint(QPainter.Antialiasing)

        for d in sorted(self._drones, key=lambda d: d.alt):
            if self._is_flashing(d) and not self._flash_on:
                continue

            sx, sy = self.lat_lon_to_screen(d.lat, d.lon)

            # Skip drones well outside the visible area
            if sx < -40 or sx > W + 40 or sy < -40 or sy > H + 40:
                continue

            heading_deg = d.heading_rad   # MQTT delivers degrees directly

            fill_color = QColor(d.name.lower())
            if not fill_color.isValid():
                fill_color = QColor(140, 140, 140)
            border_pen = white_pen

            p.save()
            p.translate(sx, sy)
            p.rotate(heading_deg)
            p.setPen(border_pen)
            p.setBrush(fill_color)
            p.drawPolygon(_ARROW)
            p.restore()

    def _on_flash_tick(self) -> None:
        self._flash_on = not self._flash_on
        if any(self._is_flashing(d) for d in self._drones):
            self.update()

    # ------------------------------------------------------------------ #
    # Tile fetching                                                        #
    # ------------------------------------------------------------------ #

    def _request_tile(self, z: int, x: int, y: int) -> None:
        key = (z, x, y)
        if key in self._cache or key in self._pending:
            return
        if time.monotonic() < self._retry_after.get(key, 0.0):
            return
        self._pending.add(key)
        threading.Thread(
            target=self._fetch_tile,
            args=(z, x, y),
            daemon=True,
        ).start()

    def set_tile_provider(self, key: str) -> None:
        """Switch satellite tile source and flush the in-memory cache."""
        if key not in TILE_PROVIDERS or key == self._provider:
            return
        self._provider = key
        self._cache.clear()
        self._pending.clear()
        self._scene_scaled_cache.clear()
        self.update()

    def _disk_path(self, z: int, x: int, y: int, provider: Optional[str] = None) -> Path:
        provider = provider or self._provider
        return TILE_PROVIDERS[provider]["cache"] / str(z) / str(x) / str(y)

    def _fetch_tile(self, z: int, x: int, y: int) -> None:
        provider = self._provider

        # 1. Disk cache
        path = self._disk_path(z, x, y, provider)
        if path.exists():
            try:
                data = path.read_bytes()
                self._tile_ready.emit(z, x, y, data)
                return
            except OSError:
                pass  # corrupt / unreadable — fall through

        # 2. Network
        url = TILE_PROVIDERS[provider]["url"].format(z=z, x=x, y=y)
        params = {"token": _ESRI_API_KEY} if _ESRI_API_KEY else None
        with _MAX_FETCH:
            try:
                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code == 404:
                    self._tile_404.emit(z, x, y)
                    return
                resp.raise_for_status()
                data = resp.content

                # Save to disk cache
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                except OSError as exc:
                    print(f"[TileMap] disk write ({z},{x},{y}): {exc}")

                self._tile_ready.emit(z, x, y, data)
            except Exception as exc:
                self._tile_error.emit(z, x, y, str(exc))

    # ------------------------------------------------------------------ #
    # Signal handlers (Qt main thread)                                    #
    # ------------------------------------------------------------------ #

    def _on_tile_ready(self, z: int, x: int, y: int, data: bytes) -> None:
        pix = QPixmap()
        pix.loadFromData(data)
        if pix.isNull():
            return
        key = (z, x, y)
        self._cache[key] = pix
        self._pending.discard(key)
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)
        self.update()

    def _on_tile_error(self, z: int, x: int, y: int, msg: str) -> None:
        key = (z, x, y)
        self._pending.discard(key)
        self._retry_after[key] = time.monotonic() + _ERROR_RETRY_COOLDOWN_S
        print(f"[TileMap] ({z},{x},{y}) {msg}")

    # ------------------------------------------------------------------ #
    # Proxy camera — nadir tile crop                                      #
    # ------------------------------------------------------------------ #

    def composite_nadir_crop(
        self,
        lat: float,
        lon: float,
        agl_m: float,
        fov_h_deg: float,
        fov_v_deg: float,
        zoom_mult: float,
        image_px: int,
    ) -> Tuple[QPixmap, bool]:
        """Composite a straight-down crop of the loaded tiles beneath (lat, lon),
        sized from altitude + FOV and narrowed by zoom_mult. Missing tiles are
        requested async and appear grey until a later call once they've arrived.

        Returns (pixmap, at_ceiling) — at_ceiling is True when the ideal zoom
        for zoom_mult was clamped to the provider's known-available max, i.e.
        zooming in further would just upscale/blur rather than sharpen."""
        agl_m = max(agl_m, 1.0)
        fov_h_deg = max(1.0, min(179.0, fov_h_deg))
        fov_v_deg = max(1.0, min(179.0, fov_v_deg))
        zoom_mult = max(1.0, zoom_mult)

        fp_w_m = 2.0 * agl_m * math.tan(math.radians(fov_h_deg / 2.0)) / zoom_mult
        fp_h_m = 2.0 * agl_m * math.tan(math.radians(fov_v_deg / 2.0)) / zoom_mult
        fp_m = max(fp_w_m, fp_h_m)

        desired_mpp = fp_m / image_px
        c = 156543.03392 * math.cos(math.radians(lat))
        ideal_zoom = int(math.ceil(math.log2(c / desired_mpp)))
        ceiling = min(_ZOOM_MAX, self._max_known_zoom)
        at_ceiling = ideal_zoom >= ceiling
        zoom = max(_ZOOM_MIN, min(ceiling, ideal_zoom))
        mpp = c / (2 ** zoom)

        ctx, cty = _ll_to_tile(lat, lon, zoom)
        crop_w = max(1.0, fp_w_m / mpp)
        crop_h = max(1.0, fp_h_m / mpp)
        half_wt = (crop_w / 2.0) / _TILE_SIZE
        half_ht = (crop_h / 2.0) / _TILE_SIZE
        tx_min = int(math.floor(ctx - half_wt))
        tx_max = int(math.ceil(ctx + half_wt))
        ty_min = int(math.floor(cty - half_ht))
        ty_max = int(math.ceil(cty + half_ht))

        n_tiles  = 2 ** zoom
        mosaic_w = (tx_max - tx_min + 1) * _TILE_SIZE
        mosaic_h = (ty_max - ty_min + 1) * _TILE_SIZE
        mosaic = QPixmap(mosaic_w, mosaic_h)
        mosaic.fill(QColor(0x50, 0x50, 0x50))

        p = QPainter(mosaic)
        for tx in range(tx_min, tx_max + 1):
            for ty in range(ty_min, ty_max + 1):
                tx_w = tx % n_tiles
                if tx_w < 0:
                    tx_w += n_tiles
                ty_c = max(0, min(n_tiles - 1, ty))
                key = (zoom, tx_w, ty_c)
                pix = self._cache.get(key)
                px  = (tx - tx_min) * _TILE_SIZE
                py  = (ty - ty_min) * _TILE_SIZE
                if pix is not None:
                    self._cache.move_to_end(key)
                    p.drawPixmap(px, py, _TILE_SIZE, _TILE_SIZE, pix)
                else:
                    self._request_tile(zoom, tx_w, ty_c)

        # Scene objects (e.g. props placed via Scene Builder) at their real
        # scale for this crop's own zoom — same width_m/mpp math as the main
        # map's _obj_screen_rect, just in mosaic-pixel space. Images are
        # flat 2D sprites with no 3D model, so they're drawn identically
        # regardless of nadir vs. stare-point viewing angle (no perspective).
        for objects in (self._scene_saved, self._scene_draft):
            for obj in sorted(objects, key=lambda o: o.get("z_order", 0)):
                obj_tx, obj_ty = _ll_to_tile(obj["lat"], obj["lon"], zoom)
                obj_px = (obj_tx - tx_min) * _TILE_SIZE
                obj_py = (obj_ty - ty_min) * _TILE_SIZE
                pw = max(obj["width_m"] / mpp, _SCENE_MIN_PX)
                img = self._get_scene_image(obj["image"])
                if img.isNull() or img.width() == 0:
                    continue
                ph = pw * img.height() / img.width()
                if (obj_px + pw / 2 < 0 or obj_px - pw / 2 > mosaic_w
                        or obj_py + ph / 2 < 0 or obj_py - ph / 2 > mosaic_h):
                    continue
                scaled = self._get_scene_scaled(obj["image"], int(pw), int(ph))
                if scaled.isNull():
                    continue
                p.drawPixmap(int(obj_px - scaled.width() / 2),
                             int(obj_py - scaled.height() / 2),
                             scaled)
        p.end()

        px_c = (ctx - tx_min) * _TILE_SIZE
        py_c = (cty - ty_min) * _TILE_SIZE
        crop_x = int(round(px_c - crop_w / 2.0))
        crop_y = int(round(py_c - crop_h / 2.0))
        crop = mosaic.copy(crop_x, crop_y, int(round(crop_w)), int(round(crop_h)))
        pixmap = crop.scaled(image_px, image_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pixmap, at_ceiling

    def _on_tile_404(self, z: int, x: int, y: int) -> None:
        """Tile source has no imagery at zoom z — roll back if we're still there,
        and remember the ceiling so later zoom-in attempts (main map or camera
        crops) don't keep re-requesting zooms the provider doesn't have."""
        key = (z, x, y)
        self._pending.discard(key)
        self._retry_after[key] = time.monotonic() + _ERROR_RETRY_COOLDOWN_S
        self._max_known_zoom = min(self._max_known_zoom, z - 1)
        if self._zoom == z:
            self._zoom = max(self._zoom - 1, _ZOOM_MIN)
            self._scene_scaled_cache.clear()
            self.update()
            self.view_changed.emit()

