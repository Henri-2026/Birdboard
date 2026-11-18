#!/usr/bin/env python3

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

import ctypes
import logging
import os
import platform
import signal
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

from beeref import constants
from beeref.assets import BeeAssets
from beeref.config import CommandlineArgs, BeeSettings, logfile_name
from beeref.view import BeeGraphicsView
from beeref.win_dwm import apply_dwm_window_shadow

logger = logging.getLogger(__name__)


class BeeRefApplication(QtWidgets.QApplication):

    def event(self, event):
        if event.type() == QtCore.QEvent.Type.FileOpen:
            for widget in self.topLevelWidgets():
                if isinstance(widget, BeeRefMainWindow):
                    widget.view.open_from_file(event.file())
                    return True
            return False
        else:
            return super().event(event)


class BeeRefMainWindow(QtWidgets.QMainWindow):

    def __init__(self, app):
        super().__init__()
        app.setOrganizationName(constants.APPNAME)
        app.setApplicationName(constants.APPNAME)
        icon = BeeAssets().logo
        app.setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.view = BeeGraphicsView(app, self)
        default_window_size = QtCore.QSize(900, 620)
        geom = self.view.settings.value('MainWindow/geometry')
        if geom is None:
            self.resize(default_window_size)
        else:
            if not self.restoreGeometry(geom):
                self.resize(default_window_size)
        self.setCentralWidget(self.view)
        self.show()
        apply_dwm_window_shadow(
            self, is_dark=(constants.ACTIVE_THEME == 'dark'))

    def closeEvent(self, event):
        geom = self.saveGeometry()
        self.view.settings.setValue('MainWindow/geometry', geom)
        self.view.prepare_for_close()
        event.accept()

    def __del__(self):
        if hasattr(self, 'view'):
            del self.view


def safe_timer(timeout, func, *args, **kwargs):
    """Create a timer that is safe against garbage collection and
    overlapping calls.
    """
    def timer_event():
        try:
            func(*args, **kwargs)
        finally:
            QtCore.QTimer.singleShot(timeout, timer_event)
    QtCore.QTimer.singleShot(timeout, timer_event)


def handle_sigint(signum, frame):
    logger.info('Received interrupt. Exiting...')
    QtWidgets.QApplication.quit()


def handle_uncaught_exception(exc_type, exc, traceback):
    logger.critical('Unhandled exception',
                    exc_info=(exc_type, exc, traceback))
    QtWidgets.QApplication.quit()


sys.excepthook = handle_uncaught_exception


def _configure_gpu_surface_format():
    fmt = QtGui.QSurfaceFormat()
    fmt.setSamples(4)
    fmt.setSwapBehavior(QtGui.QSurfaceFormat.SwapBehavior.DoubleBuffer)
    fmt.setSwapInterval(1)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)


def main():
    if sys.platform == 'win32':
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'Birdboard.ReferenceBoard.1.0')
        except Exception:
            pass

    _configure_gpu_surface_format()

    logger.info(f'Starting {constants.APPNAME} version {constants.VERSION}')
    logger.debug('System: %s', ' '.join(platform.uname()))
    logger.debug('Python: %s', platform.python_version())
    settings = BeeSettings()
    logger.info(f'Using settings: {settings.fileName()}')
    logger.info(f'Logging to: {logfile_name()}')
    settings.on_startup()
    args = CommandlineArgs(with_check=True)
    assert not args.debug_raise_error, args.debug_raise_error

    app = BeeRefApplication(sys.argv)
    bee = BeeRefMainWindow(app)  # NOQA:F841

    signal.signal(signal.SIGINT, handle_sigint)
    safe_timer(100, lambda: None)

    app.exec()
    del bee
    del app
    logger.debug('Birdboard closed')
    QtCore.qInstallMessageHandler(None)


if __name__ == '__main__':
    main()  # pragma: no cover
