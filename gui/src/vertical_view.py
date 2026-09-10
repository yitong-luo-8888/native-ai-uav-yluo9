"""
vertical_view.py — AMSL altitude vs. time graph for active drone missions.

AltitudeCollector   — records (elapsed_s, amsl) per drone while a mission runs.
AltitudeGraphWindow — floating popup that plots the collected data live.
"""

import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore    import Qt, QTimer
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    _MPL_OK = True
except ImportError:
    _MPL_OK = False

# ── colour palette (one per drone, cycles) ──────────────────────────────────
_DRONE_COLORS = [
    "#4e9af1",  # blue
    "#f17c4e",  # orange
    "#4ef18a",  # green
    "#f1e24e",  # yellow
    "#d04ef1",  # purple
    "#4ef1e2",  # cyan
    "#f14e7c",  # pink
]

_VIEW_WIDTH  = 120.0  # visible viewport width (seconds)
_SCROLL_STEP = 60.0   # seconds shifted per scroll click


# ── data collector ────────────────────────────────────────────────────────────

class AltitudeCollector:
    """
    In-memory store for drone AMSL readings.

    Call record() on the Qt main thread (via update_drone_pose) only.
    Recording starts itself on the first sample from any drone -- no
    explicit trigger (e.g. an SMP/MMP mission Launch) required, so this
    works for any live drone, including a plain MQTT/telemetry source with
    no mission-launch concept at all.
    """

    def __init__(self) -> None:
        self._start_time:  Optional[float] = None
        self._data: Dict[str, List[Tuple[float, float]]] = defaultdict(list)

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Begin or resume recording -- not required before record() (see
        below), but kept so an explicit mission Launch (where one exists)
        still gets its original behavior: the first call clears old data
        and starts the clock, later calls (a second mission, etc.) just
        resume on the same continuous timeline rather than resetting it.
        """
        if self._start_time is None:
            self._data.clear()
            self._start_time = time.monotonic()

    def record(self, drone_id: str, amsl: float) -> None:
        """Feed one telemetry sample. Starts the shared clock on the very
        first sample from any drone if start() was never called, so
        elapsed time reflects when real data actually began, not app
        startup or a Launch click that may never happen.
        """
        if self._start_time is None:
            self._start_time = time.monotonic()
        elapsed = time.monotonic() - self._start_time
        self._data[drone_id].append((elapsed, amsl))

    # ------------------------------------------------------------------ #

    @property
    def data(self) -> Dict[str, List[Tuple[float, float]]]:
        return dict(self._data)

    @property
    def is_collecting(self) -> bool:
        # No separate stop/pause state anymore (see record()'s docstring) --
        # "collecting" now just means recording has actually begun.
        return self._start_time is not None

    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time


# ── graph window ─────────────────────────────────────────────────────────────

class AltitudeGraphWindow(QWidget):
    """
    Floating window: AMSL (m) vs. elapsed time since launch.

    - Shows one coloured line per drone.
    - X-axis starts at 5 minutes; expands by 1-minute steps as needed.
    - Refreshes every second.
    - If collector already has data (previously launched mission), it is
      plotted first; live updates are added on top.
    """

    def __init__(self, collector: AltitudeCollector, parent=None) -> None:
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Altitude Profile  –  AMSL vs. Time")
        self.setMinimumSize(720, 440)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._collector   = collector
        self._color_map: Dict[str, str] = {}
        self._timer: Optional[QTimer] = None

        # Viewport state
        self._view_width = _VIEW_WIDTH
        self._live       = True
        elapsed = collector.elapsed
        # (b) drones in air: show last _view_width seconds;
        # (a) no mission yet: start from 0 — both handled by the same expression
        self._view_start = max(0.0, elapsed - self._view_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)

        if not _MPL_OK:
            layout.addWidget(QLabel(
                "matplotlib is not installed.\n\nRun:  pip install matplotlib"
            ))
            return

        # ---- matplotlib canvas ----
        self._fig = Figure(figsize=(8, 4.5), facecolor="#16161e")
        self._canvas = FigureCanvas(self._fig)
        self._ax = self._fig.add_subplot(111)
        self._fig.subplots_adjust(left=0.09, right=0.97, top=0.92, bottom=0.13)
        self._style_axes()
        layout.addWidget(self._canvas, stretch=1)

        # ---- toolbar: scroll + status ----
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 0, 4, 4)
        bar.setSpacing(6)

        _btn_style = (
            "QPushButton {"
            "  background: rgba(75,80,105,230); color: #dde;"
            "  border: 1px solid rgba(120,125,160,140);"
            "  border-radius: 4px; padding: 2px 10px; font-size: 11px;"
            "}"
            "QPushButton:hover    { background: rgba(100,105,140,255); color: #fff; }"
            "QPushButton:disabled { background: rgba(40,42,55,160); color: #55556a;"
            "  border-color: rgba(70,72,90,80); }"
        )
        _live_style = (
            "QPushButton {"
            "  background: rgba(60,110,175,230); color: #ddeeff;"
            "  border: 1px solid rgba(90,150,220,160);"
            "  border-radius: 4px; padding: 2px 10px; font-size: 11px;"
            "}"
            "QPushButton:hover    { background: rgba(80,140,210,255); color: #fff; }"
            "QPushButton:disabled { background: rgba(35,45,70,160); color: #55607a;"
            "  border-color: rgba(55,75,110,80); }"
        )

        self._back_btn = QPushButton("◀  1 min")
        self._fwd_btn  = QPushButton("1 min  ▶")
        self._live_btn = QPushButton("● Live")
        for btn in (self._back_btn, self._fwd_btn):
            btn.setStyleSheet(_btn_style)
        self._live_btn.setStyleSheet(_live_style)

        self._back_btn.clicked.connect(lambda: self._scroll(-_SCROLL_STEP))
        self._fwd_btn.clicked.connect(lambda:  self._scroll(+_SCROLL_STEP))
        self._live_btn.clicked.connect(self._go_live)

        bar.addWidget(self._back_btn)
        bar.addWidget(self._fwd_btn)
        bar.addWidget(self._live_btn)

        self._status_lbl = QLabel("Waiting for data…")
        self._status_lbl.setStyleSheet("color: #aaaabc; font-size: 10px;")
        bar.addWidget(self._status_lbl)
        bar.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(70)
        close_btn.setStyleSheet(_btn_style)
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        # ---- refresh timer ----
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

        self._refresh()

    # ------------------------------------------------------------------ #
    # Axes styling                                                         #
    # ------------------------------------------------------------------ #

    def _style_axes(self) -> None:
        ax = self._ax
        ax.set_facecolor("#0e0e18")
        ax.tick_params(colors="#909099", labelsize=8)
        ax.xaxis.label.set_color("#909099")
        ax.yaxis.label.set_color("#909099")
        ax.set_xlabel("Time since launch  (mm:ss)")
        ax.set_ylabel("Altitude AMSL  (m)")
        ax.set_title("Drone Altitude Profile", color="#c0c0cc", fontsize=10, pad=6)
        for spine in ax.spines.values():
            spine.set_edgecolor("#2a2a3a")
        ax.grid(True, color="#1e1e2e", linewidth=0.6, linestyle="--")

    # ------------------------------------------------------------------ #
    # Refresh                                                              #
    # ------------------------------------------------------------------ #

    def _scroll(self, delta: float) -> None:
        elapsed = self._collector.elapsed
        live_start = max(0.0, elapsed - self._view_width)
        new_start = max(0.0, self._view_start + delta)
        if new_start >= live_start:
            self._live = True
            new_start = live_start
        else:
            self._live = False
        self._view_start = new_start
        self._refresh()

    def _go_live(self) -> None:
        self._live = True
        elapsed = self._collector.elapsed
        self._view_start = max(0.0, elapsed - self._view_width)
        self._refresh()

    def _refresh(self) -> None:
        elapsed = self._collector.elapsed
        collecting = self._collector.is_collecting

        # Advance viewport if tracking live
        if self._live and collecting:
            self._view_start = max(0.0, elapsed - self._view_width)

        view_end = self._view_start + self._view_width

        # Update button states
        live_start = max(0.0, elapsed - self._view_width)
        self._back_btn.setEnabled(self._view_start > 0)
        self._fwd_btn.setEnabled(not self._live and self._view_start < live_start)
        self._live_btn.setEnabled(not self._live)

        self._ax.clear()
        self._style_axes()

        data = self._collector.data

        if not data:
            status = "● Recording — waiting for drone telemetry…" if collecting \
                else "No data collected yet."
            self._status_lbl.setText(status)
            self._ax.set_xlim(self._view_start, view_end)
            self._ax.set_ylim(0, 100)
            self._canvas.draw()
            return

        palette_idx = 0
        visible_amsl: List[float] = []
        for drone_id, points in sorted(data.items()):
            if drone_id not in self._color_map:
                from matplotlib.colors import is_color_like
                name_lower = drone_id.lower()
                if is_color_like(name_lower):
                    self._color_map[drone_id] = name_lower
                else:
                    self._color_map[drone_id] = _DRONE_COLORS[palette_idx % len(_DRONE_COLORS)]
                    palette_idx += 1
            color = self._color_map[drone_id]
            xs = [pt[0] for pt in points]
            ys = [pt[1] for pt in points]
            self._ax.plot(xs, ys, color=color, linewidth=1.6,
                          label=drone_id, solid_capstyle="round")
            # Collect only the altitudes visible in the current viewport for Y scaling
            visible_amsl.extend(
                pt[1] for pt in points if self._view_start <= pt[0] <= view_end
            )

        # X axis viewport
        self._ax.set_xlim(self._view_start, view_end)
        tick_step = 60 if self._view_width <= 300 else 120
        start_tick = int(self._view_start // tick_step) * tick_step
        ticks = list(range(start_tick, int(view_end) + tick_step, tick_step))
        self._ax.set_xticks(ticks)
        self._ax.set_xticklabels(
            [f"{int(t) // 60:02d}:{int(t) % 60:02d}" for t in ticks],
            fontsize=7,
        )

        # Y axis — auto-range on visible points only
        if visible_amsl:
            lo, hi = min(visible_amsl), max(visible_amsl)
            pad = max((hi - lo) * 0.10, 5.0)
            self._ax.set_ylim(lo - pad, hi + pad)
        else:
            self._ax.set_ylim(0, 100)

        self._ax.legend(
            loc="upper right", fontsize=8,
            facecolor="#1a1a28", edgecolor="#2a2a3a",
            labelcolor="#cccccc",
        )

        status = "● Recording" if collecting else "Mission ended — showing recorded data"
        self._status_lbl.setText(status)
        self._canvas.draw()

    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:
        if self._timer is not None:
            self._timer.stop()
        super().closeEvent(event)
