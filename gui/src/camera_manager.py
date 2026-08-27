"""camera_manager.py — per-drone simulated proxy camera state and nadir frame capture."""

from __future__ import annotations

import time
from enum import Enum
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap

from camera_config import CameraConfig
from drone import Drone
from tile_map import TileMap


class CameraMode(Enum):
    OFF = "OFF"
    STREAMING = "STREAMING"


_TICK_MS = 100  # master poll interval; per-drone cadence comes from config


class _CamState:
    def __init__(self, zoom: float):
        self.mode: CameraMode = CameraMode.OFF
        self.zoom: float = zoom
        self.frame: Optional[QPixmap] = None
        self.next_due: float = 0.0
        # Arm-transition AGL reference, mirrors _DroneCard.refresh()'s
        # home_alt tracking (drone_panel.py) rather than the map's static
        # base_elevation, since altitude-above-ground comes from the
        # drone's own MQTT status (home level recorded on arm).
        self.home_alt: Optional[float] = None
        self.prev_armed: Optional[bool] = None
        # True once the last capture's ideal zoom got clamped to the tile
        # provider's known-available ceiling — zooming in further wouldn't help.
        self.at_ceiling: bool = False


class CameraManager(QObject):
    """Owns per-drone simulated nadir-camera state and produces frames on a timer.

    Frame production goes through a single seam (_capture) so a future
    real-drone camera feed can be swapped in without touching mode/window/UI
    wiring elsewhere.
    """

    frame_updated = pyqtSignal(str)          # drone_name
    mode_changed  = pyqtSignal(str, object)  # drone_name, CameraMode

    def __init__(self, tile_map: TileMap, cfg: CameraConfig, parent=None):
        super().__init__(parent)
        self._tile_map = tile_map
        self._cfg = cfg
        self._states: Dict[str, _CamState] = {}
        self._drones: Dict[str, Drone] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def sync_drones(self, drones: List[Drone]) -> None:
        names = {d.name for d in drones}
        for name in list(self._states.keys()):
            if name not in names:
                del self._states[name]

        self._drones = {d.name: d for d in drones}
        for d in drones:
            state = self._states.get(d.name)
            if state is None:
                state = _CamState(self._cfg.default_zoom)
                self._states[d.name] = state
            was_armed = state.prev_armed
            state.prev_armed = d.armed
            if d.armed is True and was_armed is not True:
                state.home_alt = d.alt          # record ground level on arm
            elif d.armed is False and was_armed is True:
                state.home_alt = None           # clear on disarm

    def get_mode(self, name: str) -> CameraMode:
        state = self._states.get(name)
        return state.mode if state else CameraMode.OFF

    def set_mode(self, name: str, mode: CameraMode) -> None:
        state = self._states.get(name)
        if state is None or state.mode == mode:
            return
        state.mode = mode
        state.next_due = 0.0  # capture immediately on the next tick
        self.mode_changed.emit(name, mode)


    def get_zoom(self, name: str) -> float:
        state = self._states.get(name)
        return state.zoom if state else self._cfg.default_zoom

    def set_zoom(self, name: str, zoom: float) -> None:
        state = self._states.get(name)
        if state is None:
            return
        state.zoom = max(self._cfg.default_zoom, min(self._cfg.max_zoom, zoom))
        state.next_due = 0.0  # recapture immediately at the new zoom

    def can_zoom_in(self, name: str) -> bool:
        state = self._states.get(name)
        if state is None:
            return False
        return state.zoom < self._cfg.max_zoom and not state.at_ceiling

    def can_zoom_out(self, name: str) -> bool:
        state = self._states.get(name)
        return state is not None and state.zoom > self._cfg.default_zoom

    def zoom_in(self, name: str) -> None:
        if self.can_zoom_in(name):
            self.set_zoom(name, self._states[name].zoom * self._cfg.zoom_step)

    def zoom_out(self, name: str) -> None:
        if self.can_zoom_out(name):
            self.set_zoom(name, self._states[name].zoom / self._cfg.zoom_step)

    def zoom_reset(self, name: str) -> None:
        self.set_zoom(name, self._cfg.default_zoom)

    def get_frame(self, name: str) -> Optional[QPixmap]:
        state = self._states.get(name)
        return state.frame if state else None

    def _on_tick(self) -> None:
        now = time.monotonic()
        for name, state in self._states.items():
            if state.mode != CameraMode.STREAMING or now < state.next_due:
                continue
            state.next_due = now + self._cfg.streaming_interval_s
            drone = self._drones.get(name)
            if drone is not None:
                self._capture(drone, state)

    def _capture(self, drone: Drone, state: _CamState) -> None:
        """Produce a frame for `drone` into `state.frame`. The one seam to
        later swap in a real camera feed instead of the simulated composite."""
        if state.home_alt is None:
            state.frame = None
            return
        agl_m = drone.alt - state.home_alt
        if agl_m <= 0:
            state.frame = None
            return

        state.frame, state.at_ceiling = self._tile_map.composite_nadir_crop(
            drone.lat, drone.lon, agl_m,
            self._cfg.fov_h_deg, self._cfg.fov_v_deg,
            state.zoom, self._cfg.image_px,
        )
        self.frame_updated.emit(drone.name)
