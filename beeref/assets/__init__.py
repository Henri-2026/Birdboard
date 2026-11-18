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

from importlib.resources import files as rsc_files
import logging

from PyQt6 import QtCore, QtGui, QtWidgets


logger = logging.getLogger(__name__)


class BeeAssets:
    _instance = None
    PATH = rsc_files('beeref.assets')

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.on_new()
        return cls._instance

    def on_new(self):
        logger.debug(f'Assets path: {self.PATH}')

        logo_img = QtGui.QImage(str(self.PATH.joinpath('logo.png')))
        assert logo_img.isNull() is False
        self.logo_image = logo_img

        icon = QtGui.QIcon()
        for sz in (16, 24, 32, 48, 64, 128, 256, 512):
            scaled = logo_img.scaled(
                sz, sz,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            icon.addPixmap(QtGui.QPixmap.fromImage(scaled))
        self.logo = icon
        assert self.logo.isNull() is False

        self.cursor_rotate = self.cursor_from_image(
            'cursor_rotate.png', (20, 20))
        self.cursor_flip_h = self.cursor_from_image(
            'cursor_flip_h.png', (20, 20))
        self.cursor_flip_v = self.cursor_from_image(
            'cursor_flip_v.png', (20, 20))

    def logo_pixmap(self, size: int = 96) -> QtGui.QPixmap:
        app = QtWidgets.QApplication.instance()
        dpr = app.primaryScreen().devicePixelRatio() if app and app.primaryScreen() else 1.0
        px = max(16, round(size * dpr))
        scaled = self.logo_image.scaled(
            px, px,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        pm = QtGui.QPixmap.fromImage(scaled)
        pm.setDevicePixelRatio(dpr)
        return pm

    def cursor_from_image(self, filename, hotspot):
        app = QtWidgets.QApplication.instance()
        scaling = app.primaryScreen().devicePixelRatio()
        img = QtGui.QImage(str(self.PATH.joinpath(filename)))
        assert img.isNull() is False
        pixmap = QtGui.QPixmap.fromImage(img)
        pixmap.setDevicePixelRatio(scaling)
        return QtGui.QCursor(
            pixmap, int(hotspot[0]/scaling), int(hotspot[1]/scaling))
