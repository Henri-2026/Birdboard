# This file is part of Birdboard (GPL-3.0-or-later).

"""Windows 11 DWM rounded corners, deep window shadow, frameless resize,
and minimalist 3-dot Traffic Light window controls (scoped strictly to
Birdboard's own HWND).
"""

import ctypes
import sys

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt


class _MARGINS(ctypes.Structure):
    _fields_ = [
        ('cxLeftWidth', ctypes.c_int),
        ('cxRightWidth', ctypes.c_int),
        ('cyTopHeight', ctypes.c_int),
        ('cyBottomHeight', ctypes.c_int),
    ]


def apply_dwm_window_shadow(window: QtWidgets.QWidget, is_dark: bool = False):
    """Apply Windows 11 rounded corners + native elevation drop shadow to `window`."""
    if sys.platform != 'win32':
        return
    try:
        hwnd = int(window.winId())
        dwmapi = ctypes.windll.dwmapi

        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark_val = ctypes.c_int(1 if is_dark else 0)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark_val), ctypes.sizeof(dark_val))

        # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
        corner_pref = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))

        # DWMWA_BORDER_COLOR = 34 (COLORREF = 0x00BBGGRR)
        # Subtle 1px hairline rim so #E9EAEC or #1A1A1D separates cleanly
        # from any window behind it, surrounded by DWM's deep drop shadow.
        colorref = ctypes.c_uint32(0x003C3434 if is_dark else 0x00CCC7C4)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 34, ctypes.byref(colorref), ctypes.sizeof(colorref))

        margins = _MARGINS(1, 1, 1, 1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    except Exception:
        pass


class TrafficLightControls(QtWidgets.QWidget):
    """Compact 3-dot window controls (Close, Minimize, Maximize) in top-left."""

    DOT_RADIUS = 5.5
    DOT_SPACING = 8.0

    def __init__(self, main_window: QtWidgets.QMainWindow, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self.main_window = main_window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.hovered_idx = -1
        self._bar_hovered = False
        self.is_dark = False
        self.setFixedSize(68, 24)
        self.move(10, 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_theme(self, is_dark: bool):
        self.is_dark = is_dark
        self.update()

    def _dot_centers(self) -> list[QtCore.QPointF]:
        y = self.height() * 0.5
        start_x = 12.0
        step = self.DOT_RADIUS * 2 + self.DOT_SPACING
        return [
            QtCore.QPointF(start_x + i * step, y)
            for i in range(3)
        ]

    def _dot_at(self, pos: QtCore.QPointF) -> int:
        for i, c in enumerate(self._dot_centers()):
            if (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= (self.DOT_RADIUS + 3.0) ** 2:
                return i
        return -1

    def enterEvent(self, event):
        self._bar_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._bar_hovered = False
        self.hovered_idx = -1
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        idx = self._dot_at(event.position())
        if idx != self.hovered_idx:
            self.hovered_idx = idx
            self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._dot_at(event.position())
            if idx == 0:
                self.main_window.view.on_action_quit()
                event.accept()
                return
            if idx == 1:
                self.main_window.showMinimized()
                event.accept()
                return
            if idx == 2:
                if self.main_window.isMaximized():
                    self.main_window.showNormal()
                else:
                    self.main_window.showMaximized()
                event.accept()
                return
        event.ignore()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # Subtle frosted pill capsule behind the 3 dots
        pill_rect = QtCore.QRectF(1.0, 2.0, self.width() - 2.0, self.height() - 4.0)
        if self.is_dark:
            pill_bg = QtGui.QColor(42, 42, 48, 210 if self._bar_hovered else 155)
            pill_rim = QtGui.QColor(255, 255, 255, 34)
        else:
            pill_bg = QtGui.QColor(255, 255, 255, 225 if self._bar_hovered else 175)
            pill_rim = QtGui.QColor(0, 0, 0, 20)

        p.setPen(QtGui.QPen(pill_rim, 1.0))
        p.setBrush(pill_bg)
        p.drawRoundedRect(pill_rect, 10.0, 10.0)

        colors = [
            QtGui.QColor('#FF5F57'),  # Close
            QtGui.QColor('#FEBC2E'),  # Minimize
            QtGui.QColor('#28C840'),  # Maximize
        ]
        centers = self._dot_centers()
        for i, (c, col) in enumerate(zip(centers, colors)):
            r = self.DOT_RADIUS + (0.7 if i == self.hovered_idx else 0.0)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 32), 0.8))
            p.setBrush(col)
            p.drawEllipse(c, r, r)

            if self._bar_hovered:
                sym_pen = QtGui.QPen(QtGui.QColor(55, 20, 15, 190), 1.3)
                sym_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(sym_pen)
                if i == 0:
                    d = 2.2
                    p.drawLine(QtCore.QPointF(c.x() - d, c.y() - d),
                               QtCore.QPointF(c.x() + d, c.y() + d))
                    p.drawLine(QtCore.QPointF(c.x() + d, c.y() - d),
                               QtCore.QPointF(c.x() - d, c.y() + d))
                elif i == 1:
                    p.drawLine(QtCore.QPointF(c.x() - 2.6, c.y()),
                               QtCore.QPointF(c.x() + 2.6, c.y()))
                elif i == 2:
                    p.drawLine(QtCore.QPointF(c.x() - 2.4, c.y()),
                               QtCore.QPointF(c.x() + 2.4, c.y()))
                    p.drawLine(QtCore.QPointF(c.x(), c.y() - 2.4),
                               QtCore.QPointF(c.x(), c.y() + 2.4))

        p.end()


def detect_resize_edges(rect: QtCore.QRect, pos: QtCore.QPoint, margin: int = 6) -> Qt.Edge:
    """Return Qt.Edge bitmask if cursor is on the outer resize border."""
    edges = Qt.Edge(0)
    if pos.x() <= margin:
        edges |= Qt.Edge.LeftEdge
    elif pos.x() >= rect.width() - margin:
        edges |= Qt.Edge.RightEdge

    if pos.y() <= margin:
        edges |= Qt.Edge.TopEdge
    elif pos.y() >= rect.height() - margin:
        edges |= Qt.Edge.BottomEdge
    return edges


def cursor_for_edges(edges: Qt.Edge) -> Qt.CursorShape | None:
    if edges in (
        Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
        Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
    ):
        return Qt.CursorShape.SizeFDiagCursor
    if edges in (
        Qt.Edge.TopEdge | Qt.Edge.RightEdge,
        Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    ):
        return Qt.CursorShape.SizeBDiagCursor
    if edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
        return Qt.CursorShape.SizeHorCursor
    if edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
        return Qt.CursorShape.SizeVerCursor
    return None
