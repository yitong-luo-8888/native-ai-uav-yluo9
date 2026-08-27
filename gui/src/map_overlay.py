from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget

from map_config import MapConfig
from camera_config import CameraConfig
from camera_manager import CameraManager
from drone_panel import DronePanel, _PANEL_W
from tool_ribbon import ToolRibbon, _RIBBON_W
from tile_map import TileMap
from favorite_areas_pane  import FavoriteAreasPane
from scene_pane           import ScenePane
from vertical_view        import AltitudeCollector, AltitudeGraphWindow
from config_pane          import ConfigPane
from drone_store          import DroneStore
from camera_pane_coordinator import CameraPaneCoordinator
from camera_frame_publisher import CameraFramePublisher
from exclusive_pane_group import ExclusivePaneGroup


class MapOverlay(QWidget):
    """
    Main display widget for the map view — composition root for every
    subsystem below it. Owns Qt-shell concerns (layout, resize/key/paint
    events) and wires other components together via signals; it does not
    own drone state, camera-pane lifecycle, or pane-toggle logic anymore —
    see DroneStore, CameraPaneCoordinator, ExclusivePaneGroup.
    """

    def __init__(
        self,
        cfg: MapConfig,
        lat: float,
        lon: float,
        zoom: int = 15,
        camera_cfg: Optional[CameraConfig] = None,
    ) -> None:
        super().__init__()

        self._cfg = cfg
        self._camera_cfg = camera_cfg if camera_cfg is not None else CameraConfig()

        self.setWindowTitle("DroneResponse")
        self.setStyleSheet("background-color: #808080;")

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(cfg.tick_rate_ms)

        # ---- Altitude collector + drone store ----
        self._altitude_collector = AltitudeCollector()
        self._altitude_window: Optional[AltitudeGraphWindow] = None
        self._drone_store = DroneStore(cfg, on_pose_update=self._altitude_collector.record)

        # ---- Child widgets (ribbon | map | panel) ----
        self._ribbon = ToolRibbon(self)
        self._ribbon.show()

        self._pane_group = ExclusivePaneGroup()

        self._map_view = TileMap(lat, lon, zoom, parent=self)
        self._map_view.show()
        self._map_view.installEventFilter(self)
        self._drone_store.add_consumer(self._map_view.set_drones)

        # Proxy camera — only exists at all when simulation=True in config,
        # so real-world deployments have zero footprint from this feature.
        # Up to _CAM_SLOT_COUNT panes can be open at once, each anchored to
        # a "home slot" (stacked top-to-bottom); dragging a pane away from
        # its slot frees that slot for reuse while the pane keeps streaming.
        self._camera_manager: Optional[CameraManager] = (
            CameraManager(self._map_view, self._camera_cfg) if self._camera_cfg.simulation else None
        )
        self._cam_coordinator: Optional[CameraPaneCoordinator] = None
        if self._camera_manager is not None:
            self._cam_coordinator = CameraPaneCoordinator(
                self._camera_manager, self._camera_cfg,
                parent=self, map_geometry=self._map_geometry,
            )
            self._drone_store.add_consumer(self._camera_manager.sync_drones)

        self._cam_frame_publisher: Optional[CameraFramePublisher] = None
        if self._camera_manager is not None:
            self._cam_frame_publisher = CameraFramePublisher(
                self._camera_manager, self._drone_store, self._camera_cfg,
            )

        self._panel: Optional[DronePanel] = None
        if cfg.show_panel:
            self._panel = DronePanel(
                self, cfg.panel_side,
                camera_manager=self._camera_manager,
                on_camera_click=self._cam_coordinator.on_camera_click if self._cam_coordinator else None,
            )
            self._panel.show()
            self._drone_store.add_consumer(self._panel.update_drones)

        self._scene_pane = ScenePane(
            on_draft_changed=self._on_scene_draft_changed,
            on_display_changed=self._on_scene_display_changed,
            parent=self,
        )
        self._pane_group.register(
            self._ribbon.btn_scene, self._scene_pane,
            on_shown=lambda: self._map_view.set_scene_mode(True),
            on_hidden=lambda: self._map_view.set_scene_mode(False),
        )
        self._map_view.scene_drop_requested.connect(
            lambda rp, lat, lon: self._scene_pane.on_object_dropped(rp, lat, lon)
        )
        self._map_view.scene_object_moved.connect(
            lambda idx, lat, lon: self._scene_pane.on_object_moved(idx, lat, lon)
        )
        self._map_view.scene_object_clicked.connect(
            lambda idx: self._scene_pane.on_object_clicked(idx)
        )
        self._map_view.scene_object_right_clicked.connect(
            lambda idx: self._scene_pane.on_object_right_clicked(idx)
        )
        self._fav_pane = FavoriteAreasPane(
            self._map_view,
            parent=self,
        )
        self._pane_group.register(self._ribbon.btn_regions, self._fav_pane)
        self._fav_pane.apply_default()

        # ---- Config pane ----
        self._config_pane = ConfigPane(parent=self)
        self._config_pane.map_heading_changed.connect(self._map_view.set_map_heading)
        self._config_pane.tile_provider_changed.connect(self._on_tile_provider_changed)
        self._config_pane.start_heading_pick.connect(
            lambda: self._map_view.set_heading_pick_mode(True)
        )
        self._config_pane.cancel_heading_pick.connect(
            lambda: self._map_view.set_heading_pick_mode(False)
        )
        self._map_view.heading_pick_step_changed.connect(self._config_pane.on_heading_pick_step)
        self._map_view.heading_arrow_shown.connect(self._config_pane.on_heading_arrow_shown)
        self._config_pane.accept_heading_arrow.connect(self._map_view.accept_heading_arrow)
        self._map_view.heading_pick_complete.connect(self._on_heading_pick_complete)
        self._config_pane.hide()   # ConfigPane, unlike FavoriteAreasPane/ScenePane, doesn't self-hide
        self._pane_group.register(self._ribbon.btn_config, self._config_pane)

        self._ribbon.btn_altitude.clicked.connect(self._on_altitude_chart)

    # -------------------- Configuration pane --------------------

    def _on_heading_pick_complete(self, degrees: int) -> None:
        self._config_pane.set_heading_from_pick(degrees)

    # -------------------- Scene pane --------------------

    def _on_scene_draft_changed(self, draft: list) -> None:
        self._map_view.set_scene_draft(draft)

    def _on_scene_display_changed(self, objects: list) -> None:
        self._map_view.set_scene_saved(objects)

    def eventFilter(self, obj, event) -> bool:
        if (obj is self._map_view
                and event.type() == QEvent.MouseButtonPress
                and self._altitude_window is not None):
            self._altitude_window.close()
        return False

    def _on_altitude_chart(self) -> None:
        """Open (or raise) the altitude profile graph window."""
        if self._altitude_window is None:
            self._altitude_window = AltitudeGraphWindow(
                self._altitude_collector, parent=self
            )
            self._altitude_window.destroyed.connect(
                lambda: setattr(self, "_altitude_window", None)
            )
            self._altitude_window.show()
        else:
            self._altitude_window.show()
            self._altitude_window.raise_()
            self._altitude_window.activateWindow()

    def _on_tile_provider_changed(self, key: str) -> None:
        self._map_view.set_tile_provider(key)

    # -------------------- Layout --------------------

    def _map_geometry(self):
        """Return (x, y, w, h) for the MapView between ribbon and panel."""
        panel_w = _PANEL_W if self._panel else 0
        x = _RIBBON_W
        w = max(1, self.width() - _RIBBON_W - panel_w)
        return x, 0, w, self.height()

    # -------------------- Tick --------------------

    def _on_tick(self) -> None:
        self._drone_store.poll()

    # -------------------- Qt event handlers --------------------

    def resizeEvent(self, ev):
        self._ribbon.reposition()
        self._map_view.setGeometry(*self._map_geometry())
        if self._panel is not None:
            self._panel.reposition()
        if self._fav_pane.isVisible():
            self._fav_pane.reposition()
        if self._scene_pane.isVisible():
            self._scene_pane.reposition()
        if self._cam_coordinator is not None:
            self._cam_coordinator.reposition_panes()
        return super().resizeEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close()
        elif ev.key() == Qt.Key_F:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else:
            super().keyPressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def paintEvent(self, ev):
        # Background only shows through gaps (if any); MapView covers the centre.
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0x80, 0x80, 0x80))
        p.end()

    # -------------------- MQTT --------------------

    def start_mqtt(self) -> None:
        self._drone_store.start_mqtt()

    def stop_mqtt(self) -> None:
        self._drone_store.stop_mqtt()

    def closeEvent(self, ev):
        self.stop_mqtt()
        if self._panel is not None:
            self._panel.close()
        super().closeEvent(ev)
