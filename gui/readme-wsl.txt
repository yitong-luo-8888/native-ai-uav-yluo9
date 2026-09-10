WSL2 setup notes
================

Qt's "xcb" platform plugin depends on several system shared libraries that
are not installed by default on WSL2, even though DISPLAY/WAYLAND_DISPLAY
are already set correctly by WSLg. Without them, the app fails with:

    qt.qpa.plugin: Could not load the Qt platform plugin "xcb" in ""
    Aborted (core dumped)

To find exactly which library is missing, check the xcb plugin's
dependencies with ldd:

    ldd .venv/lib/python3.12/site-packages/PyQt5/Qt5/plugins/platforms/libqxcb.so | grep "not found"

Confirmed fix on this machine: the plugin was missing libxcb-shape.so.0.

    sudo apt-get update && sudo apt-get install -y libxcb-shape0

If ldd reports other missing libraries, this broader set covers the usual
PyQt5/xcb requirements on WSL2:

    sudo apt-get install -y libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-cursor0 libxcb-xkb1 libxkbcommon-x11-0 libgl1 libegl1 libdbus-1-3
