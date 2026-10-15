#!/usr/bin/env python3
"""gui_autostart.py -- new-gui, with the two R7 clicks done for you.

Builds the same window as gui/src/new-gui.py (that file is not modified), then:

  1. Scene Builder: shows ONLY the saved scene --scene (hides the others) and
     draws it on the map -- what toggling it in the Scene Builder does.
  2. Centres the map on the search area.
  3. Once drone --drone (UAV 1 = "Fuchsia") appears, turns its camera to
     STREAMING through the same handler as the drone card's [C] button, so
     its camera pane opens and frames go out on VIDEO_STREAM/<drone>/frame.

The camera records the ground level when it sees the drone ARM, so start
this before the drone takes off (run_demo.sh restarts SITL 1 first).

    python hw07/tools/gui_autostart.py [--scene lost-boy-north-gate] [--drone Fuchsia]
"""
import argparse
import os
import signal
import sys

GUI_SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gui", "src"))
sys.path.insert(0, GUI_SRC)

from PyQt5.QtCore import QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from camera_config import CameraConfig  # noqa: E402
from map_config import MapConfig  # noqa: E402
from map_overlay import MapOverlay  # noqa: E402


def log(message):
    print(f"[gui] {message}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", default="lost-boy-north-gate")
    parser.add_argument("--drone", default="Fuchsia", help="drone name whose camera to stream (UAV 1 = Fuchsia)")
    parser.add_argument("--lat", type=float, default=41.69940)
    parser.add_argument("--lon", type=float, default=-86.23705)
    parser.add_argument("--zoom", type=int, default=19)
    args = parser.parse_args()

    camera_cfg = CameraConfig.from_file(os.path.join(GUI_SRC, "camera.config"))
    if not camera_cfg.simulation:
        sys.exit("gui/src/camera.config has simulation=false: no simulated camera to stream")
    app = QApplication(sys.argv)
    w = MapOverlay(MapConfig(), lat=args.lat, lon=args.lon, zoom=args.zoom, camera_cfg=camera_cfg)

    # 1. the scene: same state change and redraw as the Scene Builder's toggle button
    scenes = w._scene_pane._saved
    if not any(s["name"] == args.scene for s in scenes):
        sys.exit(f"No saved scene {args.scene!r} in gui/src/data/scene/saved/ -- run scenario_to_scene.py first")
    for s in scenes:
        s["visible"] = s["name"] == args.scene
    w._scene_pane._rebuild_scene_rows()
    w._scene_pane._push_display_changed()
    log(f"scene {args.scene!r} shown ({sum(len(s['objects']) for s in scenes if s['visible'])} objects)")

    # 3. the camera: press the drone card's [C] once the drone exists
    pressed = []

    def on_drones(drones):
        if pressed or not any(d.name == args.drone for d in drones):
            return
        pressed.append(True)
        QTimer.singleShot(500, lambda: (w._cam_coordinator.on_camera_click(args.drone),
                                        log(f"camera {args.drone}: {w._camera_manager.get_mode(args.drone).value}")))

    w._drone_store.add_consumer(on_drones)
    w._camera_manager.frame_updated.connect(
        lambda name: None if getattr(w, "_first_frame", False) else
        (setattr(w, "_first_frame", True), log(f"first camera frame from {name} published")))

    w.start_mqtt()
    w.showMaximized()
    # 2. FavoriteAreasPane.apply_default() re-centred the map during construction; centre on the search area
    QTimer.singleShot(300, lambda: w._map_view.set_center(args.lat, args.lon, args.zoom))
    log("window up")

    signal.signal(signal.SIGINT, lambda *_: w.close())
    signal.signal(signal.SIGTERM, lambda *_: w.close())
    keepalive = QTimer()
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
