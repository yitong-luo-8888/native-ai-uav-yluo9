"""
tool_ribbon.py — Narrow vertical icon ribbon anchored to the left edge.

Implemented as a child widget of MapOverlay (not a top-level window) using
the same approach as DronePanel: plain QWidget + QVBoxLayout, no QScrollArea,
so it stays an "alien" widget sharing the parent's X11 window on WSL2/WSLg.
"""

import os
from PyQt5.QtCore    import Qt, QSize, QObject, QEvent, QPoint
from PyQt5.QtGui     import QIcon, QPixmap, QColor, QPalette
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QToolButton, QFrame, QLabel



_RIBBON_W  = 48          # wide enough for a 32 px icon with 8 px side padding
_ICON_SIZE = 32
_DARK_BG   = "rgba(30, 30, 30, 210)"   # matches DronePanel
_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")

_BTN_STYLE = (
    "QToolButton         { border: none; background: transparent; }"
    "QToolButton:hover   { background: rgba(255,255,255,30); border-radius: 4px; }"
    "QToolButton:checked { background: rgba(40,75,130,180); border-radius: 4px; }"
)


class _RibbonTip(QLabel):
    """Custom tooltip label — bypasses Qt's system tooltip rendering on WSLg."""
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QLabel {"
            "  background-color: #f0f0f0;"
            "  color: #222222;"
            "  border: 1px solid #bbbbbb;"
            "  padding: 2px 6px;"
            "  font-size: 11px;"
            "}"
        )
        p = self.palette()
        p.setColor(QPalette.Window,     QColor("#f0f0f0"))
        p.setColor(QPalette.WindowText, QColor("#222222"))
        self.setPalette(p)
        self.setAutoFillBackground(True)

    def show_at(self, pos: QPoint, text: str):
        self.setText(text)
        self.adjustSize()
        self.move(pos)
        self.show()
        self.raise_()


class _RibbonTooltipFilter(QObject):
    """Shows ribbon-button tooltips at a fixed position: right of the button, slightly raised."""
    def __init__(self):
        super().__init__()
        self._tip = _RibbonTip()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ToolTip and isinstance(obj, QToolButton):
            pos = obj.mapToGlobal(QPoint(obj.width() + 8, obj.height() // 2 - 8))
            self._tip.show_at(pos, obj.toolTip())
            return True
        if event.type() in (QEvent.Leave, QEvent.MouseButtonPress):
            self._tip.hide()
        return super().eventFilter(obj, event)


_TOOLTIP_FILTER = None   # created once ToolRibbon is instantiated (after QApplication exists)


def _make_button(icon_name: str, tooltip: str, parent: QWidget,
                 checkable: bool = False) -> QToolButton:
    btn = QToolButton(parent)
    path = os.path.join(_ICONS_DIR, icon_name)
    btn.setIcon(QIcon(QPixmap(path)))
    btn.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
    btn.setFixedSize(_ICON_SIZE, _ICON_SIZE)
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setStyleSheet(_BTN_STYLE)
    return btn



def _make_divider(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    line.setStyleSheet("color: rgba(255,255,255,60);")
    line.setFixedHeight(1)
    return line


class ToolRibbon(QWidget):
    """
    Thin vertical ribbon on the left edge of the parent widget.

    Public button attributes (connect to their .clicked signal):
      btn_regions,
      btn_altitude, btn_scene,
      btn_config
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        global _TOOLTIP_FILTER
        if _TOOLTIP_FILTER is None:
            _TOOLTIP_FILTER = _RibbonTooltipFilter()

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {_DARK_BG};")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignHCenter)

        self.btn_regions  = _make_button("regions.png",  "Regions",       self, checkable=True)
        self.btn_altitude    = _make_button("elevation.png", "Altitude Profile", self)
        self.btn_scene       = _make_button("scene.png",     "Scene Builder",    self, checkable=True)
        self.btn_config   = _make_button("config.png",   "Configuration", self, checkable=True)

        for item in [
            self.btn_config,
            None,                   # divider
            self.btn_regions,
            self.btn_altitude,
            None,                   # divider
            self.btn_scene,
        ]:
            if item is None:
                self._layout.addWidget(_make_divider(self))
            else:
                item.installEventFilter(_TOOLTIP_FILTER)
                self._layout.addWidget(item)

        self._layout.addStretch(1)

    def reposition(self) -> None:
        """Snap geometry to the left edge of the parent widget."""
        p = self.parent()
        self.setGeometry(0, 0, _RIBBON_W, p.height())
        self.raise_()
