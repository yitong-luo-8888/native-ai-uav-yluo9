#!/usr/bin/env python3
"""
dronemap.py — Root-level launcher for the DroneResponse student GUI.

Actual application code lives in src/. This just hands off to
src/new-gui.py, forwarding any command-line arguments unchanged:

    python dronemap.py [path to config JSON]
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP  = os.path.join(_HERE, "src", "new-gui.py")

os.execv(sys.executable, [sys.executable, _APP, *sys.argv[1:]])
