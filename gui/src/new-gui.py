#!/usr/bin/env python3

# Usage guide:
#   python dronemap.py [path to config JSON]
#   eg: python dronemap.py south-quad.json
#
#   Minimal config JSON (all fields optional):
#   {
#     "broker": "localhost",
#     "topic": "update_drone",
#     "show_panel": true,
#     "windowed": true,
#     "width": 1280,
#     "height": 720
#   }
#
#   Proxy-camera / simulation settings are separate and universal: see
#   camera.config next to this script (not passed on the command line).

import signal
import sys
import argparse
from pathlib import Path

from PyQt5.QtCore    import QTimer
from PyQt5.QtGui     import QColor, QPalette
from PyQt5.QtWidgets import QApplication

from camera_config import CameraConfig
from map_config import MapConfig
from map_overlay import MapOverlay

# ---- Default map location (replace later with favorites JSON) ----
_DEFAULT_LAT  = 41.755404799377445
_DEFAULT_LON  = -86.1910162161972
_DEFAULT_ZOOM = 17


def main():
    #load_dotenv()

    parser = argparse.ArgumentParser(
        description="Map viewer with MQTT-driven drone status panel."
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to config JSON (optional; all settings have defaults)",
    )
    args = parser.parse_args()

    cfg = MapConfig.from_file(args.config) if args.config else MapConfig()

    # Universal proxy-camera / simulation settings — same regardless of which
    # flight-region config was passed above.
    camera_cfg_path = Path(__file__).parent / "camera.config"
    camera_cfg = CameraConfig.from_file(str(camera_cfg_path))

    app = QApplication(sys.argv)
    app.setStyleSheet(
        "QToolTip {"
        "  background-color: #f0f0f0;"
        "  color: #222222;"
        "  border: 1px solid #bbbbbb;"
        "  padding: 2px 5px;"
        "  font-size: 11px;"
        "}"
    )
    _palette = app.palette()
    _palette.setColor(QPalette.ToolTipBase, QColor("#f0f0f0"))
    _palette.setColor(QPalette.ToolTipText, QColor("#222222"))
    app.setPalette(_palette)

    w = MapOverlay(
        cfg,
        lat=_DEFAULT_LAT,
        lon=_DEFAULT_LON,
        zoom=_DEFAULT_ZOOM,
        camera_cfg=camera_cfg,
    )
    w.start_mqtt()
    w.showMaximized()

    # Allow Ctrl+C to trigger a clean closeEvent (stops MQTT, closes panels)
    signal.signal(signal.SIGINT, lambda *_: w.close())
    # Qt blocks in C++ so Python signals need a periodic nudge to be delivered
    sigint_timer = QTimer()
    sigint_timer.start(200)
    sigint_timer.timeout.connect(lambda: None)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
