#!/usr/bin/env python3

# This file is part of Birdboard (based on BeeRef, GPL-3.0-or-later).

from importlib.resources import files as rsc_files
import logging
import os

from PyQt6 import QtCore, QtGui, QtSvg, QtWidgets


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
        self._svg_cache: dict[tuple, QtGui.QPixmap] = {}
        self.ui_font_family = 'Segoe UI'
        self._register_bundled_fonts()

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

    def _register_bundled_fonts(self):
        fonts_dir = str(self.PATH.joinpath('fonts'))
        if not os.path.isdir(fonts_dir):
            return
        loaded_families = set()
        for fn in os.listdir(fonts_dir):
            if fn.lower().endswith('.ttf'):
                fid = QtGui.QFontDatabase.addApplicationFont(
                    os.path.join(fonts_dir, fn))
                if fid >= 0:
                    for fam in QtGui.QFontDatabase.applicationFontFamilies(fid):
                        loaded_families.add(fam)
        if 'Be Vietnam Pro' in loaded_families:
            self.ui_font_family = 'Be Vietnam Pro'
            logger.info('Loaded bundled font family: Be Vietnam Pro')
        elif loaded_families:
            self.ui_font_family = sorted(loaded_families)[0]

    def font(
        self,
        pixel_size: int = 14,
        weight: int = 400,
        italic: bool = False,
    ) -> QtGui.QFont:
        f = QtGui.QFont(self.ui_font_family)
        f.setPixelSize(max(8, int(pixel_size)))
        if weight <= 320:
            f.setWeight(QtGui.QFont.Weight.Light)
        elif weight <= 450:
            f.setWeight(QtGui.QFont.Weight.Normal)
        elif weight <= 650:
            f.setWeight(QtGui.QFont.Weight.DemiBold)
        else:
            f.setWeight(QtGui.QFont.Weight.Bold)
        f.setItalic(italic)
        f.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
        return f

    def svg_icon_pixmap(
        self,
        icon_name: str,
        size: int = 19,
        color: QtGui.QColor | str = '#F5F6F7',
        opacity: float = 1.0,
    ) -> QtGui.QPixmap:
        if isinstance(color, str):
            color = QtGui.QColor(color)
        app = QtWidgets.QApplication.instance()
        dpr = (
            app.primaryScreen().devicePixelRatio()
            if app and app.primaryScreen() else 1.0
        )
        cache_key = (icon_name, size, color.rgba(), round(opacity, 3), round(dpr, 2))
        cached = self._svg_cache.get(cache_key)
        if cached is not None:
            return cached

        svg_path = str(self.PATH.joinpath('icons').joinpath(f'{icon_name}.svg'))
        px = max(8, round(size * dpr))
        img = QtGui.QImage(
            px, px, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(QtCore.Qt.GlobalColor.transparent)

        if os.path.exists(svg_path):
            try:
                with open(svg_path, 'r', encoding='utf-8') as f:
                    svg_txt = f.read()
                hex_rgb = color.name(QtGui.QColor.NameFormat.HexRgb)
                svg_txt = svg_txt.replace('currentColor', hex_rgb)
                renderer = QtSvg.QSvgRenderer(
                    QtCore.QByteArray(svg_txt.encode('utf-8')))
                painter = QtGui.QPainter(img)
                painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                painter.setOpacity(max(0.0, min(1.0, opacity)))
                renderer.render(painter, QtCore.QRectF(0, 0, size, size))
                painter.end()
            except Exception:
                logger.exception(f'Failed rendering SVG icon {icon_name}')

        pm = QtGui.QPixmap.fromImage(img)
        self._svg_cache[cache_key] = pm
        return pm

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
            pixmap, int(hotspot[0] / scaling), int(hotspot[1] / scaling))
