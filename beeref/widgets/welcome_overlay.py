# This file is part of Birdboard (based on BeeRef).
#
# BeeRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BeeRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BeeRef.  If not, see <https://www.gnu.org/licenses/>.

import logging
import os.path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import constants
from beeref.assets import BeeAssets
from beeref.config import BeeSettings
from beeref.main_controls import MainControlsMixin
from beeref.win_dwm import cursor_for_edges, detect_resize_edges


logger = logging.getLogger(__name__)


class RecentFilesModel(QtCore.QAbstractListModel):
    """An entry in the 'Recent Files' list."""

    def __init__(self, files):
        super().__init__()
        self.files = files

    def rowCount(self, parent):
        return len(self.files)

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return os.path.basename(self.files[index.row()])
        if role == QtCore.Qt.ItemDataRole.FontRole:
            font = QtGui.QFont()
            font.setUnderline(True)
            return font


class RecentFilesView(QtWidgets.QListView):

    def __init__(self, parent, view, files=None):
        super().__init__(parent)
        self.view = view
        self.files = files or []
        self.clicked.connect(self.on_clicked)
        self.setModel(RecentFilesModel(self.files))
        self.setMouseTracking(True)

    def on_clicked(self, index):
        self.view.open_from_file(self.files[index.row()])

    def update_files(self, files):
        self.files = files
        self.model().files = files
        self.reset()

    def sizeHint(self):
        size = QtCore.QSize()
        if not self.files:
            return size
        height = sum(
            (self.sizeHintForRow(i) + 2) for i in range(len(self.files)))
        width = max(self.sizeHintForColumn(i) for i in range(len(self.files)))
        size.setHeight(height)
        size.setWidth(width + 2)
        return size

    def mouseMoveEvent(self, event):
        index = self.indexAt(
            QtCore.QPoint(int(event.position().x()),
                          int(event.position().y())))
        if index.isValid():
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)


class WelcomeOverlay(MainControlsMixin, QtWidgets.QWidget):
    """Displayed when the canvas is empty."""

    txt = """<p style="font-size: 13px;">Paste or drop images here.</p>
             <p style="color: #9e9e9e;">Right-click for more options.</p>"""

    def __init__(self, parent):
        super().__init__(parent)
        self.control_target = parent
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)
        self.init_main_controls(main_window=parent.parent)

        # Recent files
        self.files_widget = QtWidgets.QWidget(self)
        files_layout = QtWidgets.QVBoxLayout()
        files_layout.addStretch(50)
        files_layout.addWidget(
            QtWidgets.QLabel('<h3>Recent Files</h3>', self))
        self.files_view = RecentFilesView(self, parent)
        files_layout.addWidget(self.files_view)
        files_layout.addStretch(50)
        self.files_widget.setLayout(files_layout)
        self.files_widget.hide()

        # Center Logo + Help text
        center_widget = QtWidgets.QWidget(self)
        center_layout = QtWidgets.QVBoxLayout()
        center_layout.addStretch(50)

        self.logo_label = QtWidgets.QLabel(self)
        self.logo_label.setPixmap(BeeAssets().logo_pixmap(92))
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.logo_label)
        center_layout.addSpacing(10)

        self.label = QtWidgets.QLabel(self.txt, self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignVCenter
                                | Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.label)
        center_layout.addStretch(50)
        center_widget.setLayout(center_layout)
        self.center_widget = center_widget

        self.layout = QtWidgets.QHBoxLayout()
        self.layout.addStretch(50)
        self.layout.addWidget(center_widget)
        self.layout.addStretch(50)
        self.setLayout(self.layout)
        self.apply_theme()

    def apply_theme(self):
        t = constants.get_active_theme()
        bg = t['Welcome:Bg']
        fg = t['Welcome:TextPrimary']
        sec = t['Welcome:TextSecondary']
        self.setStyleSheet(
            f'WelcomeOverlay {{ background-color: {bg}; }}'
            f'QLabel {{ color: {fg}; background: transparent; }}'
            f'QListView {{ color: {fg}; background: transparent; border: none; }}'
        )
        self.label.setText(
            f'<p style="font-size: 13px; color: {fg};">Paste or drop images here.</p>'
            f'<p style="color: {sec};">Right-click for more options.</p>'
        )

    def show(self):
        files = BeeSettings().get_recent_files(existing_only=True)
        self.files_view.update_files(files)
        if files and self.layout.indexOf(self.files_widget) < 0:
            self.layout.insertWidget(0, self.files_widget)
            self.files_widget.show()
        super().show()
        self.raise_()

    def disable_mouse_events(self):
        self.files_view.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.logo_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def enable_mouse_events(self):
        self.files_view.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            on=False)
        self.logo_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            on=False)
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            on=False)

    def mousePressEvent(self, event):
        mw = self.main_window
        if (event.button() == Qt.MouseButton.LeftButton
                and bool(mw.windowFlags() & Qt.WindowType.FramelessWindowHint)
                and not mw.isMaximized()
                and not mw.isFullScreen()):
            win_pos = self.mapTo(mw, event.pos())
            edges = detect_resize_edges(mw.rect(), win_pos, margin=6)
            wh = mw.windowHandle()
            if edges and wh is not None:
                wh.startSystemResize(edges)
                event.accept()
                return
            if win_pos.y() <= 32 and wh is not None:
                wh.startSystemMove()
                event.accept()
                return

        if self.mousePressEventMainControls(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        mw = self.main_window
        if (not self.movewin_active
                and bool(mw.windowFlags() & Qt.WindowType.FramelessWindowHint)
                and not mw.isMaximized()
                and not mw.isFullScreen()):
            win_pos = self.mapTo(mw, event.pos())
            edges = detect_resize_edges(mw.rect(), win_pos, margin=6)
            edge_cur = cursor_for_edges(edges)
            if edge_cur is not None:
                self.setCursor(edge_cur)
                self._resize_cur = True
                return
            elif getattr(self, '_resize_cur', False):
                self._resize_cur = False
                self.unsetCursor()

        if self.mouseMoveEventMainControls(event):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mouseReleaseEventMainControls(event):
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.keyPressEventMainControls(event):
            return
        super().keyPressEvent(event)
