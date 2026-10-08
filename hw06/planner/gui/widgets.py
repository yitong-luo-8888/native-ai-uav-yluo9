"""widgets.py -- the dashboard's views. They only draw a MissionMirror
(dashboard.py); none of them publishes anything or knows about MQTT.

  MapView     top-down map in metres east/north of the route centre
  Legend      marker/status key for the map
  StatePanel  UAV state, persons table, selected-person detail
  LogPane     timestamped mission/* traffic, coloured by direction
"""
from __future__ import annotations

import html
import math
import time

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QAbstractItemView, QFormLayout, QGraphicsItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QTableWidget, QTableWidgetItem, QTextBrowser,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..world_model import enu_m

STATUS_COLORS = {
    "unknown": "#9e9e9e",     # seen, no decision yet (or timed out)
    "pending": "#f0a500",     # decision_request outstanding
    "approved": "#1e6fd9",    # response approved / executing
    "dismissed": "#6d4c41",   # operator chose "No action"
    "rejected": "#c0392b",    # last choice rejected; being re-asked
    "completed": "#2e8b57",   # response finished
}
STATE_COLORS = {"PENDING": "#b8860b", "RUNNING": "#1e6fd9", "COMPLETED": "#2e8b57",
                "FAILED": "#c0392b", "CANCELLED": "#7f8c8d"}
DIRECTION_COLORS = {
    "detector→planner": "#6a1b9a",
    "planner→operator": "#1565c0",
    "operator→planner": "#2e7d32",
}
ROUTE_COLOR = "#455a64"
SEGMENT_COLOR = "#00acc1"
RESUME_COLOR = "#e65100"
UAV_COLOR = "#d81b60"
RING_COLOR = "#7b1fa2"


def _pen(color: str, width: float = 1.5, style=Qt.SolidLine) -> QPen:
    pen = QPen(QColor(color), width, style)
    pen.setCosmetic(True)          # width in pixels at any zoom
    return pen


class _Label(QGraphicsSimpleTextItem):
    """Text that stays the same pixel size at any zoom."""

    def __init__(self, text: str, color: str = "#212121", size: int = 9, bold: bool = False):
        super().__init__(text)
        font = QFont()
        font.setPointSize(size)
        font.setBold(bold)
        self.setFont(font)
        self.setBrush(QBrush(QColor(color)))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)


class MapView(QGraphicsView):
    """Scene units are metres: x = east, y = -north (so north is up)."""

    location_picked = pyqtSignal(float, float)    # double-click -> (lat, lon)

    GRID_STEP_M = 25.0
    MARGIN_M = 45.0

    def __init__(self, mirror, parent=None):
        super().__init__(parent)
        self.mirror = mirror
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#fafafa")))
        self.setMinimumSize(560, 420)
        self.follow = False
        self._user_zoomed = False
        self._dynamic: list[QGraphicsItem] = []
        wps = [wp for route in mirror.routes.values() for wp in route]
        if wps:
            self.origin = (sum(w.lat for w in wps) / len(wps), sum(w.lon for w in wps) / len(wps))
        else:
            self.origin = (0.0, 0.0)
        self._bounds = self._route_bounds()
        self._draw_static()

    # -- coordinates -----------------------------------------------------------
    def xy(self, lat: float, lon: float) -> QPointF:
        east, north = enu_m(self.origin[0], self.origin[1], lat, lon)
        return QPointF(east, -north)

    def latlon(self, p: QPointF) -> tuple[float, float]:
        lat0, lon0 = self.origin
        lat = lat0 + math.degrees(-p.y() / 6378137.0)
        lon = lon0 + math.degrees(p.x() / (6378137.0 * math.cos(math.radians(lat0))))
        return lat, lon

    def _route_bounds(self) -> QRectF:
        pts = [self.xy(w.lat, w.lon) for route in self.mirror.routes.values() for w in route]
        if not pts:
            return QRectF(-100, -100, 200, 200)
        xs, ys = [p.x() for p in pts], [p.y() for p in pts]
        m = self.MARGIN_M
        return QRectF(min(xs) - m, min(ys) - m, max(xs) - min(xs) + 2 * m, max(ys) - min(ys) + 2 * m)

    # -- static layer: grid, axes, route ----------------------------------------
    def _draw_static(self) -> None:
        scene, b, step = self.scene(), self._bounds, self.GRID_STEP_M
        grid_pen = _pen("#e0e0e0", 1)
        x0, x1 = math.floor(b.left() / step) * step, math.ceil(b.right() / step) * step
        y0, y1 = math.floor(b.top() / step) * step, math.ceil(b.bottom() / step) * step
        x = x0
        while x <= x1:
            scene.addLine(x, y0, x, y1, grid_pen)
            lbl = _Label(f"{x:.0f}", "#757575", 8)
            lbl.setPos(x, y1)
            scene.addItem(lbl)
            x += step
        y = y0
        while y <= y1:
            scene.addLine(x0, y, x1, y, grid_pen)
            lbl = _Label(f"{-y + 0.0:.0f}", "#757575", 8)
            lbl.setPos(x0, y)
            scene.addItem(lbl)
            y += step
        for text, pos in (("East (m) →", QPointF(x1 - step * 1.5, y1 - step * 0.4)),
                          ("↑ North (m)", QPointF(x0 + step * 0.3, y0 + step * 0.1))):
            lbl = _Label(text, "#424242", 9, bold=True)
            lbl.setPos(pos)
            scene.addItem(lbl)
        scene.setSceneRect(QRectF(x0 - step * 2, y0 - step * 2, (x1 - x0) + step * 4, (y1 - y0) + step * 4))

        for route in self.mirror.routes.values():
            path = QPainterPath()
            for i, wp in enumerate(route):
                p = self.xy(wp.lat, wp.lon)
                path.moveTo(p) if i == 0 else path.lineTo(p)
            scene.addPath(path, _pen(ROUTE_COLOR, 1.5, Qt.DashLine))
            for i, wp in enumerate(route):
                p = self.xy(wp.lat, wp.lon)
                scene.addEllipse(p.x() - 1.2, p.y() - 1.2, 2.4, 2.4, _pen(ROUTE_COLOR, 1), QBrush(QColor("white")))
                lbl = _Label(str(i + 1), ROUTE_COLOR, 8, bold=True)
                lbl.setPos(p.x() + 1.5, p.y() - 1.5)
                scene.addItem(lbl)

    # -- dynamic layer --------------------------------------------------------------
    def _add(self, item: QGraphicsItem) -> QGraphicsItem:
        self._dynamic.append(item)
        return item

    def _ring(self, center: QPointF, r: float, color: str, style=Qt.DashLine, width: float = 2):
        return self._add(self.scene().addEllipse(center.x() - r, center.y() - r, 2 * r, 2 * r, _pen(color, width, style)))

    def _text(self, text: str, pos: QPointF, color: str, size: int = 9, bold: bool = False):
        lbl = _Label(text, color, size, bold)
        lbl.setPos(pos)
        self.scene().addItem(lbl)
        return self._add(lbl)

    def refresh(self) -> None:
        scene = self.scene()
        for item in self._dynamic:
            scene.removeItem(item)
        self._dynamic = []
        m = self.mirror
        for uav, route in m.routes.items():
            u = m.uavs.get(uav)
            if not route or u is None:
                continue
            idx = u.route_index
            if idx is not None and 0 <= idx < len(route) and u.response is None:
                # current segment: previous waypoint (or the UAV) -> the waypoint it's heading to
                start = self.xy(u.lat, u.lon) if u.lat is not None else self.xy(route[idx - 1].lat, route[idx - 1].lon)
                end = self.xy(route[idx].lat, route[idx].lon)
                self._add(scene.addLine(start.x(), start.y(), end.x(), end.y(), _pen(SEGMENT_COLOR, 4)))
            if u.resume_index is not None and 0 <= u.resume_index < len(route):
                p = self.xy(route[u.resume_index].lat, route[u.resume_index].lon)
                diamond = QPolygonF([QPointF(p.x(), p.y() - 5), QPointF(p.x() + 5, p.y()),
                                     QPointF(p.x(), p.y() + 5), QPointF(p.x() - 5, p.y())])
                self._add(scene.addPolygon(diamond, _pen(RESUME_COLOR, 3), QBrush(QColor(255, 152, 0, 70))))
                self._text(f"RESUME → wp {u.resume_index + 1}", QPointF(p.x() + 5, p.y() + 3), RESUME_COLOR, 9, True)

        for p in m.person_rows():
            pt = self.xy(p["lat"], p["lon"])
            color = STATUS_COLORS[p["status"]]
            dot = scene.addEllipse(-6, -6, 12, 12, _pen("#212121", 1), QBrush(QColor(color)))
            dot.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            dot.setPos(pt)
            self._add(dot)
            self._text(f"{p['id']} {p['confidence']:.2f} {p['status']}", QPointF(pt.x() + 2, pt.y() + 2), color, 8, True)

        for uav, u in m.uavs.items():
            r = u.response
            if r is not None and r.get("target") and r.get("state") in ("PENDING", "RUNNING"):
                c = self.xy(r["target"]["lat"], r["target"]["lon"])
                params = r.get("parameters") or {}
                if r["type"] == "hover_stream":
                    self._ring(c, float(params.get("standoff_m") or 0) or 2.0, RING_COLOR)
                    self._text(f"hover standoff {float(params.get('standoff_m') or 0):g} m",
                               QPointF(c.x() + 3, c.y() - 12), RING_COLOR, 8)
                elif r["type"] == "circle_stream":
                    rad = float(params.get("radius_m") or 15)
                    self._ring(c, rad, RING_COLOR, Qt.SolidLine)
                    self._add(scene.addEllipse(c.x() - 1.5, c.y() - rad - 1.5, 3, 3, _pen(RING_COLOR, 1),
                                               QBrush(QColor(RING_COLOR))))
                    self._text(f"orbit r={rad:g} m (entry N)", QPointF(c.x() + 3, c.y() - rad - 10), RING_COLOR, 8)
                elif r["type"] == "deliver":
                    alt = u.alt_rel if u.alt_rel is not None else 20.0
                    self._ring(c, max(1.5, alt * 0.75), RING_COLOR, Qt.SolidLine, 2.5)
                    self._text(f"deliver: alt {alt:.1f} m", QPointF(c.x() + 3, c.y() - 12), RING_COLOR, 9, True)
            if len(u.trail) > 1:
                path = QPainterPath()
                for i, (lat, lon) in enumerate(u.trail):
                    p = self.xy(lat, lon)
                    path.moveTo(p) if i == 0 else path.lineTo(p)
                self._add(scene.addPath(path, _pen("#f48fb1", 1.5)))
            if u.lat is not None:
                pos = self.xy(u.lat, u.lon)
                arrow = scene.addPolygon(QPolygonF([QPointF(0, -13), QPointF(8, 9), QPointF(0, 4), QPointF(-8, 9)]),
                                         _pen("#212121", 1), QBrush(QColor(UAV_COLOR)))
                arrow.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                arrow.setPos(pos)
                arrow.setRotation(u.heading or 0.0)     # compass heading: clockwise from north
                self._add(arrow)
                self._text(f"UAV {uav}", QPointF(pos.x() + 3, pos.y() + 3), UAV_COLOR, 9, True)
                if self.follow:
                    self.centerOn(pos)

    # -- view behaviour ------------------------------------------------------------------
    def fit_route(self) -> None:
        self.fitInView(self._bounds, Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._user_zoomed:
            self.fit_route()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._user_zoomed:
            self.fit_route()

    def wheelEvent(self, event):
        self._user_zoomed = True
        factor = 1.15 ** (event.angleDelta().y() / 120)
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event):
        lat, lon = self.latlon(self.mapToScene(event.pos()))
        self.location_picked.emit(lat, lon)


class Legend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        items = [(f"● {name}", color) for name, color in STATUS_COLORS.items()]
        items += [("▲ UAV", UAV_COLOR), ("━ current segment", SEGMENT_COLOR), ("◆ resume waypoint", RESUME_COLOR),
                  ("◯ response ring", RING_COLOR), ("┄ search route", ROUTE_COLOR)]
        row.addWidget(QLabel("<b>Legend:</b>"))
        for text, color in items:
            lbl = QLabel(f"<span style='color:{color}; font-weight:bold'>{html.escape(text)}</span>")
            row.addWidget(lbl)
        row.addStretch(1)


class StatePanel(QWidget):
    person_selected = pyqtSignal(str)

    COLUMNS = ["id", "lat", "lon", "conf", "source", "status", "action_id"]

    def __init__(self, mirror, parent=None):
        super().__init__(parent)
        self.mirror = mirror
        self.selected: str | None = None
        layout = QVBoxLayout(self)

        self.uav_box = QGroupBox("UAV")
        form = QFormLayout(self.uav_box)
        self.position = QLabel("—")
        self.battery = QProgressBar()
        self.battery.setRange(0, 100)
        self.battery.setFormat("%p%")
        self.payload = QLabel("—")
        self.behavior = QLabel("—")
        self.route = QLabel("—")
        self.response = QLabel("—")
        self.response.setWordWrap(True)
        for name, w in (("Position", self.position), ("Battery", self.battery), ("Payload", self.payload),
                        ("Current behavior", self.behavior), ("Route progress", self.route),
                        ("Response", self.response)):
            form.addRow(name, w)
        layout.addWidget(self.uav_box)

        persons_box = QGroupBox("Persons")
        pv = QVBoxLayout(persons_box)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        pv.addWidget(self.table)
        layout.addWidget(persons_box, 2)

        detail_box = QGroupBox("Selected person")
        dv = QVBoxLayout(detail_box)
        self.detail = QTextBrowser()
        dv.addWidget(self.detail)
        layout.addWidget(detail_box, 2)

    def _on_select(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.selected = self.table.item(rows[0].row(), 0).text()
            self.person_selected.emit(self.selected)
            self._refresh_detail()

    def refresh(self) -> None:
        m = self.mirror
        u = next(iter(m.uavs.values()), None)
        if u is not None:
            self.uav_box.setTitle(f"UAV {u.uav} ({u.color})")
            if u.lat is not None:
                self.position.setText(f"{u.lat:.6f}, {u.lon:.6f}  alt {u.alt_rel or 0:.1f} m  hdg {u.heading or 0:.0f}°")
            if u.battery_level is not None:
                self.battery.setValue(int(round(u.battery_level * 100)))
            self.payload.setText(", ".join(u.payloads) or "none")
            self.behavior.setText(u.current_behavior or "—")
            n = len(m.routes.get(u.uav, []))
            idx = f"heading to waypoint {u.route_index + 1} of {n}" if u.route_index is not None else "—"
            if u.resume_index is not None:
                idx += f"  (resume at {u.resume_index + 1})"
            self.route.setText(idx)
            r = u.response
            if r:
                color = STATE_COLORS.get(r.get("state"), "black")
                self.response.setText(f"{r['type']} <b style='color:{color}'>{r.get('state')}</b> "
                                      f"[{r['action_id']}] — {html.escape(r.get('detail') or '')}")
            else:
                self.response.setText("none")

        rows = m.person_rows()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, p in enumerate(rows):
            values = [p["id"], f"{p['lat']:.6f}", f"{p['lon']:.6f}", f"{p['confidence']:.2f}",
                      p["source"], p["status"], p["action_id"] or ""]
            for j, v in enumerate(values):
                item = QTableWidgetItem(v)
                if j == 5:
                    item.setForeground(QBrush(QColor(STATUS_COLORS[p["status"]])))
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(i, j, item)
            if p["id"] == self.selected:
                self.table.selectRow(i)
        self.table.blockSignals(False)
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        p = self.mirror.person_detail(self.selected) if self.selected else None
        if p is None:
            self.detail.setHtml("<i>Select a person in the table.</i>")
            return
        parts = [f"<b>{p['id']}</b> — status <b style='color:{STATUS_COLORS[p['status']]}'>{p['status']}</b>, "
                 f"confidence {p['confidence']:.2f}, {p['sightings']} sighting(s), events {', '.join(p['event_ids'])}"]
        if p["candidates"]:
            parts.append("<b>Candidate menu</b> (last request):<ul>")
            for c in p["candidates"]:
                params = ", ".join(f"{k}={v}" for k, v in c.get("parameters", {}).items())
                parts.append(f"<li><b>{html.escape(c['type'])}</b> on {', '.join(c['eligible_uavs'])} "
                             f"(default {c.get('default_uav')}): {html.escape(params)}</li>")
            parts.append("</ul>")
        if p["last_result"]:
            r = p["last_result"]
            verdict = "<b style='color:#2e8b57'>APPROVED</b>" if r["approved"] else "<b style='color:#c0392b'>REJECTED</b>"
            reasons = " ".join(r.get("reasons") or []) or "(no reasons)"
            parts.append(f"<b>Last action_result:</b> {verdict} {r.get('type')} on UAV {r.get('uav')} — {html.escape(reasons)}")
        self.detail.setHtml("<br>".join(parts))


class LogPane(QTextEdit):
    MAX_LINES = 1500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(self.MAX_LINES)
        font = QFont("monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.setFont(font)
        legend = "  ".join(f"<span style='color:{c}'>■ {d}</span>" for d, c in DIRECTION_COLORS.items())
        self.append(f"<b>mission/* log</b> &nbsp; {legend}")

    def add(self, direction: str, topic: str, summary: str, when: float | None = None) -> None:
        stamp = time.strftime("%H:%M:%S", time.localtime(when or time.time()))
        color = DIRECTION_COLORS.get(direction, "#424242")
        self.append(f"<span style='color:#757575'>{stamp}</span> "
                    f"<span style='color:{color}'><b>{html.escape(direction):>18}</b> "
                    f"{html.escape(topic)}</span> {html.escape(summary)}")
