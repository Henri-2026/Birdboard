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

"""Classes for items that are added to the scene by the user (images,
text).
"""

from collections import defaultdict
from functools import cached_property
import logging
import math
import os.path
import pathlib
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import commands, constants
from beeref.config import BeeSettings
from beeref.constants import COLORS
from beeref.lod_cache import (
    LODCacheManager,
    LODImagePayload,
    LOD_MID_MAX,
    LOD_THUMB_MAX,
    build_payload_from_bytes,
    decode_from_bytes,
    decode_from_path,
    encode_thumb_jpeg_or_png,
    fetch_sqlar_blob,
)
from beeref.selection import SelectableMixin


logger = logging.getLogger(__name__)

item_registry = {}
_CARD_SHADOW_ATLAS_CACHE: dict[int, QtGui.QPixmap] = {}
_SHADOW_ATLAS_SZ = 128
_SHADOW_BOX_INSET = 28
_SHADOW_SLICE_M = 42


def _get_card_shadow_atlas(peak_alpha: int) -> QtGui.QPixmap:
    """Build & cache a 128x128 C++ Gaussian-blurred 9-patch shadow atlas (~64 KB)."""
    cached = _CARD_SHADOW_ATLAS_CACHE.get(peak_alpha)
    if cached is not None:
        return cached

    sz = _SHADOW_ATLAS_SZ
    ins = _SHADOW_BOX_INSET
    src_pm = QtGui.QPixmap(sz, sz)
    src_pm.fill(Qt.GlobalColor.transparent)
    sp = QtGui.QPainter(src_pm)
    sp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    sp.setPen(Qt.PenStyle.NoPen)
    sp.setBrush(QtGui.QColor(0, 0, 0, peak_alpha))
    sp.drawRoundedRect(
        QtCore.QRectF(float(ins), float(ins), float(sz - 2 * ins), float(sz - 2 * ins)),
        2.0,
        2.0,
    )
    sp.end()

    sc = QtWidgets.QGraphicsScene(0.0, 0.0, float(sz), float(sz))
    pm_item = QtWidgets.QGraphicsPixmapItem(src_pm)
    blur = QtWidgets.QGraphicsBlurEffect()
    blur.setBlurRadius(13.5)
    blur.setBlurHints(QtWidgets.QGraphicsBlurEffect.BlurHint.QualityHint)
    pm_item.setGraphicsEffect(blur)
    sc.addItem(pm_item)

    img = QtGui.QImage(sz, sz, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    op = QtGui.QPainter(img)
    op.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    sc.render(
        op,
        QtCore.QRectF(0.0, 0.0, float(sz), float(sz)),
        QtCore.QRectF(0.0, 0.0, float(sz), float(sz)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
    )
    op.end()

    out_pm = QtGui.QPixmap.fromImage(img)
    _CARD_SHADOW_ATLAS_CACHE[peak_alpha] = out_pm
    return out_pm


def _draw_soft_card_shadow(painter: QtGui.QPainter, rect: QtCore.QRectF, px_unit: float, is_dark: bool):
    """Paint a silky-smooth 9-patch Gaussian shadow beneath `rect` (zero hard edges)."""
    if rect.width() <= 0.0 or rect.height() <= 0.0:
        return
    peak_alpha = 112 if is_dark else 46
    atlas = _get_card_shadow_atlas(peak_alpha)

    pad = max(18.0, 0.045 * max(rect.width(), rect.height()))
    y_shift = min(3.8 * px_unit, pad * 0.12)
    box = rect.translated(0.0, y_shift)
    in_raw = float(_SHADOW_SLICE_M - _SHADOW_BOX_INSET)  # 14.0
    out_raw = float(_SHADOW_BOX_INSET)                   # 28.0
    scale_s = min(
        0.88 * px_unit,
        (pad * 0.85) / out_raw,
        box.width() / (2.3 * in_raw),
        box.height() / (2.3 * in_raw),
    )
    if scale_s <= 1e-6:
        return

    out_p = out_raw * scale_s
    in_p = in_raw * scale_s
    xs = (box.left() - out_p, box.left() + in_p, box.right() - in_p, box.right() + out_p)
    ys = (box.top() - out_p, box.top() + in_p, box.bottom() - in_p, box.bottom() + out_p)
    s_coords = (0.0, float(_SHADOW_SLICE_M), float(_SHADOW_ATLAS_SZ - _SHADOW_SLICE_M), float(_SHADOW_ATLAS_SZ))

    for r in range(3):
        dy = ys[r + 1] - ys[r]
        if dy <= 0.0:
            continue
        sy = s_coords[r]
        sh = s_coords[r + 1] - sy
        for c in range(3):
            dx = xs[c + 1] - xs[c]
            if dx <= 0.0:
                continue
            sx = s_coords[c]
            sw = s_coords[c + 1] - sx
            painter.drawPixmap(
                QtCore.QRectF(xs[c], ys[r], dx, dy),
                atlas,
                QtCore.QRectF(sx, sy, sw, sh),
            )


def register_item(cls):
    item_registry[cls.TYPE] = cls
    return cls


def sort_by_filename(items):
    """Order items by filename.

    Items with a filename (ordered by filename) first, then items
    without a filename but with a save_id follow (ordered by
    save_id), then remaining items in the order that they have
    been inserted into the scene.
    """

    items_by_filename = []
    items_by_save_id = []
    items_remaining = []

    for item in items:
        if getattr(item, 'filename', None):
            items_by_filename.append(item)
        elif getattr(item, 'save_id', None):
            items_by_save_id.append(item)
        else:
            items_remaining.append(item)

    items_by_filename.sort(key=lambda x: x.filename)
    items_by_save_id.sort(key=lambda x: x.save_id)
    return items_by_filename + items_by_save_id + items_remaining


class BeeItemMixin(SelectableMixin):
    """Base for all items added by the user."""

    def set_pos_center(self, pos):
        """Sets the position using the item's center as the origin point."""

        self.setPos(pos - self.center_scene_coords)

    def has_selection_outline(self):
        if not self.isSelected():
            return False
        sc = self.scene()
        if (sc is not None
                and getattr(self, 'stack_id', None)
                and hasattr(sc, 'stack_manager')
                and sc.stack_manager.active_spread_stack_id != self.stack_id):
            return False
        return True

    def has_selection_handles(self):
        return (self.isSelected()
                and self.scene()
                and self.scene().has_single_selection())

    def selection_action_items(self):
        """The items affected by selection actions like scaling and rotating.
        """
        return [self]

    def on_selected_change(self, value):
        if (value and self.scene()
                and not self.scene().in_batch_update
                and not self.scene().has_selection()
                and self.scene().active_mode is not None):
            self.bring_to_front()

    def update_from_data(self, **kwargs):
        self.save_id = kwargs.get('save_id', self.save_id)
        self.setPos(kwargs.get('x', self.pos().x()),
                    kwargs.get('y', self.pos().y()))
        self.setZValue(kwargs.get('z', self.zValue()))
        self.setScale(kwargs.get('scale', self.scale()))
        self.setRotation(kwargs.get('rotation', self.rotation()))
        if kwargs.get('flip', 1) != self.flip():
            self.do_flip()


@register_item
class BeePixmapItem(BeeItemMixin, QtWidgets.QGraphicsPixmapItem):
    """High-performance LOD-backed image item for massive reference boards."""

    TYPE = 'pixmap'
    CROP_HANDLE_SIZE = 15

    def __init__(self, image=None, filename=None, payload: LODImagePayload | None = None, **kwargs):
        super().__init__()
        self.save_id = None
        self.filename = filename
        self.is_image = True
        self.crop_mode = False
        self.settings = BeeSettings()
        self._grayscale = False
        self._gray_cache: tuple[int, QtGui.QPixmap] | None = None

        self._orig_width = 0
        self._orig_height = 0
        self._exif_trans = 0
        self._img_format = ''
        self._source_path: str | None = filename if (filename and os.path.exists(str(filename))) else None
        self._source_bytes: bytes | None = None
        self._bee_source: tuple[str, int] | None = None
        self.thumb_pixmap = QtGui.QPixmap()

        # Stack Group & Detail Stage metadata
        self.stack_id: str | None = None
        self.is_stack_cover: bool = False
        self.stack_order: int = 0
        self.stack_name: str = ''
        self.custom_title: str = ''
        self.note: str = ''
        self.palette_hex: list[str] = []
        self.stack_saved_scale: float | None = None
        self.stack_saved_rot: float | None = None
        self._hover_inside: bool = False
        self._hover_lift: float = 0.0
        self._hover_target: float = 0.0
        self._hover_from: float = 0.0
        self._hover_t0: float = 0.0

        if self._source_path:
            try:
                self.created_ts: float = os.path.getctime(self._source_path)
            except OSError:
                self.created_ts = time.time()
        else:
            self.created_ts = time.time()

        if payload is not None:
            self._apply_lod_payload(payload)
        elif image is not None and not image.isNull():
            self._init_from_qimage(image)
        else:
            self._crop = QtCore.QRectF(0, 0, 0, 0)

        self.init_selectable()
        logger.debug(f'Initialized {self}')

    @classmethod
    def from_lod_payload(cls, payload: LODImagePayload, filename=None) -> 'BeePixmapItem':
        return cls(image=None, filename=filename or payload.source_path, payload=payload)

    def _apply_lod_payload(self, payload: LODImagePayload):
        self._orig_width = payload.orig_width
        self._orig_height = payload.orig_height
        self._exif_trans = payload.exif_trans
        self._img_format = payload.img_format
        if payload.source_path:
            self._source_path = payload.source_path
        self._source_bytes = payload.source_bytes
        self._bee_source = payload.bee_source
        self.thumb_pixmap = QtGui.QPixmap.fromImage(payload.thumb_image)
        self._gray_cache = None
        self.reset_crop()

    def _init_from_qimage(self, image: QtGui.QImage):
        self._orig_width = image.width()
        self._orig_height = image.height()
        max_dim = max(self._orig_width, self._orig_height)
        if max_dim > LOD_THUMB_MAX:
            thumb_img = image.scaled(
                LOD_THUMB_MAX,
                LOD_THUMB_MAX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumb_pixmap = QtGui.QPixmap.fromImage(thumb_img)
            # Put full pixmap into bounded LRU cache
            LODCacheManager.instance().put_full_pixmap(
                self, QtGui.QPixmap.fromImage(image))
            # If image has no disk file backing (e.g. pasted from clipboard),
            # store compressed bytes so RAM can still be evicted safely later.
            if not self._source_path:
                ba = QtCore.QByteArray()
                buf = QtCore.QBuffer(ba)
                buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
                fmt = self.get_imgformat(image)
                image.save(buf, fmt.upper(), quality=92)
                buf.close()
                self._source_bytes = bytes(ba.data())
                self._img_format = fmt
        else:
            self.thumb_pixmap = QtGui.QPixmap.fromImage(image)
        self._gray_cache = None
        self.reset_crop()

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.pop('data', {})
        payload = kwargs.pop('payload', None)
        item = kwargs.pop('item', None)
        if item is None:
            if payload is not None:
                item = cls.from_lod_payload(
                    payload, filename=data.get('filename'))
            else:
                item = cls(QtGui.QImage(), filename=data.get('filename'))

        item.filename = item.filename or data.get('filename')
        if 'crop' in data:
            item.crop = QtCore.QRectF(*data['crop'])
        item.setOpacity(data.get('opacity', 1))
        item.grayscale = data.get('grayscale', False)
        item.stack_id = data.get('stack_id')
        item.is_stack_cover = bool(data.get('is_stack_cover', False))
        item.stack_order = int(data.get('stack_order', 0))
        item.stack_name = str(data.get('stack_name', '') or '')
        item.custom_title = str(data.get('custom_title', '') or '')
        item.note = str(data.get('note', '') or '')
        item.palette_hex = list(data.get('palette_hex', []) or [])
        if data.get('created_ts'):
            item.created_ts = float(data['created_ts'])
        if data.get('stack_saved_scale') is not None:
            item.stack_saved_scale = float(data['stack_saved_scale'])
        if data.get('stack_saved_rot') is not None:
            item.stack_saved_rot = float(data['stack_saved_rot'])
        return item

    def __str__(self):
        return (f'Image "{self.filename}" '
                f'{self._orig_width} x {self._orig_height}')

    @property
    def orig_size(self) -> QtCore.QSize:
        return QtCore.QSize(self._orig_width, self._orig_height)

    @property
    def max_orig_edge(self) -> int:
        return max(self._orig_width, self._orig_height)

    def get_source_spec(self) -> dict:
        return {
            'bytes': self._source_bytes,
            'path': self._source_path,
            'bee_source': self._bee_source,
            'thumb_pixmap': self.thumb_pixmap,
        }

    def set_bee_source(self, bee_filepath: str, save_id: int):
        self._bee_source = (bee_filepath, save_id)
        # Once backed by a saved .bee file on disk, drop in-RAM compressed blob
        # if there is no local file path so memory stays minimal.
        if os.path.exists(bee_filepath):
            self._source_bytes = None

    def decode_source_qimage(self, max_edge: int | None = None) -> QtGui.QImage:
        """Synchronously decode QImage at requested max_edge (or full-res)."""
        if self.max_orig_edge <= LOD_THUMB_MAX and not self.thumb_pixmap.isNull():
            return self.thumb_pixmap.toImage()

        if self._source_bytes:
            img, *_ = decode_from_bytes(self._source_bytes, max_edge=max_edge)
            if not img.isNull():
                return img

        if self._source_path and os.path.exists(self._source_path):
            img, *_ = decode_from_path(self._source_path, max_edge=max_edge)
            if not img.isNull():
                return img

        if self._bee_source:
            blob = fetch_sqlar_blob(self._bee_source[0], self._bee_source[1])
            if blob:
                img, *_ = decode_from_bytes(blob, max_edge=max_edge)
                if not img.isNull():
                    return img

        return self.thumb_pixmap.toImage()

    def pixmap(self) -> QtGui.QPixmap:
        """Return full-resolution QPixmap (loaded on demand if evicted)."""
        if self._orig_width <= 0 or self._orig_height <= 0:
            return QtGui.QPixmap()
        if self.max_orig_edge <= LOD_THUMB_MAX:
            return self.thumb_pixmap
        return LODCacheManager.instance().get_best_pixmap(
            self, desired_tier=2, sync_if_missing=True)

    def on_lod_ready(self):
        self._gray_cache = None
        self.update()

    def on_lod_evicted(self):
        self._gray_cache = None

    @property
    def crop(self):
        return self._crop

    @crop.setter
    def crop(self, value):
        logger.debug(f'Setting crop for {self} to {value}')
        self.prepareGeometryChange()
        self._crop = value
        if self.scene():
            self.scene().invalidate_bounds_cache()
        self.update()

    @property
    def grayscale(self):
        return self._grayscale

    @grayscale.setter
    def grayscale(self, value):
        self._grayscale = bool(value)
        if not self._grayscale:
            self._gray_cache = None
        self.update()

    def _to_grayscale_pixmap(self, pm: QtGui.QPixmap) -> QtGui.QPixmap:
        if pm.isNull():
            return pm
        key = pm.cacheKey()
        if self._gray_cache is not None and self._gray_cache[0] == key:
            return self._gray_cache[1]

        img = QtGui.QImage(
            pm.size(), QtGui.QImage.Format.Format_Grayscale8)
        img.fill(QtGui.QColor(*COLORS['Scene:Canvas']))
        painter = QtGui.QPainter(img)
        painter.drawPixmap(0, 0, pm)
        painter.end()
        gpm = QtGui.QPixmap.fromImage(img)
        self._gray_cache = (key, gpm)
        return gpm

    def sample_color_at(self, pos):
        if self._orig_width <= 0 or self._orig_height <= 0:
            return None
        ipos = self.mapFromScene(pos)
        if not self.bounding_rect_unselected().contains(ipos):
            return None

        # Use highest currently-resident LOD pixmap without stalling mouse move
        mgr = LODCacheManager.instance()
        pm = (mgr.full_cache.get(id(self))
              or mgr.mid_cache.get(id(self))
              or self.thumb_pixmap)
        if pm.isNull():
            return None
        if self.grayscale:
            pm = self._to_grayscale_pixmap(pm)

        sx = pm.width() / self._orig_width
        sy = pm.height() / self._orig_height
        px = min(pm.width() - 1, max(0, int(ipos.x() * sx)))
        py = min(pm.height() - 1, max(0, int(ipos.y() * sy)))
        # Copy only a 1x1 pixel rect instead of converting the entire 4K QPixmap!
        one_px = pm.copy(px, py, 1, 1).toImage()
        color = one_px.pixelColor(0, 0)
        if color.alpha():
            return color
        return None

    def bounding_rect_unselected(self):
        if self.crop_mode:
            return QtCore.QRectF(0, 0, self._orig_width, self._orig_height)
        return self.crop

    def contains(self, point):
        return self.bounding_rect_unselected().contains(point)

    def get_extra_save_data(self):
        extra = {
            'filename': self.filename,
            'opacity': self.opacity(),
            'grayscale': self.grayscale,
            'crop': [
                self.crop.topLeft().x(),
                self.crop.topLeft().y(),
                self.crop.width(),
                self.crop.height(),
            ],
            'created_ts': self.created_ts,
        }
        if self.stack_id:
            extra['stack_id'] = self.stack_id
            extra['is_stack_cover'] = self.is_stack_cover
            extra['stack_order'] = self.stack_order
            if self.stack_name:
                extra['stack_name'] = self.stack_name
            if self.stack_saved_scale is not None:
                extra['stack_saved_scale'] = self.stack_saved_scale
            if self.stack_saved_rot is not None:
                extra['stack_saved_rot'] = self.stack_saved_rot
        if self.custom_title:
            extra['custom_title'] = self.custom_title
        if self.note:
            extra['note'] = self.note
        if self.palette_hex:
            extra['palette_hex'] = self.palette_hex
        return extra

    @property
    def display_filename(self) -> str:
        if self.custom_title:
            return self.custom_title
        if self.filename:
            base = os.path.basename(str(self.filename))
            if base:
                return base
        ext = self._img_format if self._img_format in ('jpg', 'png') else 'png'
        return f'Image.{ext}'

    def _is_collapsed_stack_cover(self) -> bool:
        if not (self.stack_id and self.is_stack_cover):
            return False
        sc = self.scene()
        if sc and hasattr(sc, 'stack_manager'):
            if sc.stack_manager.active_spread_stack_id == self.stack_id:
                return False
        return True

    def _collapsed_pile_local_rect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF(self.crop)
        sc = self.scene()
        if sc and hasattr(sc, 'stack_manager') and self.stack_id:
            for m in sc.stack_manager.visible_pile_members_fast(self.stack_id):
                if m is not self:
                    rect = rect.united(self.mapRectFromItem(m, m.crop))
        return rect

    def boundingRect(self):
        r = self.bounding_rect_unselected()
        pad = max(18.0, 0.045 * max(r.width(), r.height()))
        padded = r.adjusted(-pad, -pad, pad, pad * 1.15)
        if self.has_selection_handles():
            return padded.united(super().boundingRect())
        return padded

    def hit_spread_cover_badge(self, item_pos: QtCore.QPointF) -> bool:
        sc = self.scene()
        if not (self.stack_id and sc and hasattr(sc, 'stack_manager')):
            return False
        if sc.stack_manager.active_spread_stack_id != self.stack_id:
            return False
        diam = self.fixed_length_for_viewport(24.0)
        pad = self.fixed_length_for_viewport(10.0)
        badge_r = QtCore.QRectF(
            self.crop.left() + pad,
            self.crop.top() + pad,
            diam,
            diam,
        )
        return badge_r.adjusted(-pad * 0.3, -pad * 0.3, pad * 0.3, pad * 0.3).contains(item_pos)

    def get_thumb_save_bytes(self) -> bytes:
        """Encoded Tier-0 thumbnail bytes for instant .bee project loading."""
        if self.thumb_pixmap.isNull():
            return b''
        return encode_thumb_jpeg_or_png(self.thumb_pixmap.toImage())

    def get_filename_for_export(self, imgformat, save_id_default=None):
        save_id = self.save_id or save_id_default
        assert save_id is not None

        chosen_name = self.custom_title or self.filename
        if chosen_name:
            basename = os.path.splitext(os.path.basename(str(chosen_name)))[0]
            return f'{save_id:04}-{basename}.{imgformat}'
        else:
            return f'{save_id:04}.{imgformat}'

    def get_imgformat(self, img):
        """Determines the format for storing this image."""

        formt = self.settings.valueOrDefault('Items/image_storage_format')

        if formt == 'best':
            if (img.hasAlphaChannel()
                    or (img.height() < 500 and img.width() < 500)):
                formt = 'png'
            else:
                formt = 'jpg'

        logger.debug(f'Found format {formt} for {self}')
        return formt

    def pixmap_to_bytes(self, apply_grayscale=False, apply_crop=False):
        """Convert image data to compressed PNG/JPG bytestring (zero-reencode fast path)."""
        if not apply_grayscale and not apply_crop:
            pref_fmt = self.settings.valueOrDefault('Items/image_storage_format')

            # Fast path 1: Already have encoded bytes in memory
            if self._source_bytes and self._img_format in ('jpg', 'png'):
                if pref_fmt in ('best', self._img_format):
                    return (self._source_bytes, self._img_format)

            # Fast path 2: Backed by unmodified local JPG/PNG file (no EXIF rotation needed)
            if (self._source_path
                    and self._exif_trans == 0
                    and self._img_format in ('jpg', 'png')
                    and os.path.exists(self._source_path)):
                if pref_fmt == self._img_format or (
                        pref_fmt == 'best' and self._img_format == 'jpg'):
                    try:
                        raw = pathlib.Path(self._source_path).read_bytes()
                        return (raw, self._img_format)
                    except OSError:
                        pass

            # Fast path 3: Backed by existing .bee sqlar archive
            if self._bee_source and pref_fmt == 'best':
                blob = fetch_sqlar_blob(self._bee_source[0], self._bee_source[1])
                if blob:
                    fmt = self._img_format if self._img_format in ('jpg', 'png') else (
                        'png' if blob[:8] == b'\x89PNG\r\n\x1a\n' else 'jpg')
                    return (blob, fmt)

        # General path: decode lossless source and encode
        img = self.decode_source_qimage(max_edge=None)
        if apply_grayscale and self.grayscale:
            g_img = QtGui.QImage(
                img.size(), QtGui.QImage.Format.Format_Grayscale8)
            g_img.fill(QtGui.QColor(*COLORS['Scene:Canvas']))
            p = QtGui.QPainter(g_img)
            p.drawImage(0, 0, img)
            p.end()
            img = g_img

        if apply_crop:
            img = img.copy(self.crop.toRect())

        barray = QtCore.QByteArray()
        buffer = QtCore.QBuffer(barray)
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        imgformat = self.get_imgformat(img)
        img.save(buffer, imgformat.upper(), quality=90)
        buffer.close()
        return (bytes(barray.data()), imgformat)

    def setPixmap(self, pixmap):
        LODCacheManager.instance().evict_item(self)
        if pixmap is None or pixmap.isNull():
            self.prepareGeometryChange()
            self._orig_width = 0
            self._orig_height = 0
            self.thumb_pixmap = QtGui.QPixmap()
            self._crop = QtCore.QRectF(0, 0, 0, 0)
            return
        self._init_from_qimage(pixmap.toImage())

    def pixmap_from_bytes(self, data: bytes, bee_source: tuple[str, int] | None = None):
        """Initialize LOD-backed image from compressed PNG/JPG bytes."""
        LODCacheManager.instance().evict_item(self)
        payload = build_payload_from_bytes(
            data, bee_source=bee_source, keep_bytes=(bee_source is None))
        if payload is not None:
            self._apply_lod_payload(payload)
        else:
            self.prepareGeometryChange()
            self._orig_width = 0
            self._orig_height = 0
            self.thumb_pixmap = QtGui.QPixmap()
            self._crop = QtCore.QRectF(0, 0, 0, 0)

    def create_copy(self):
        item = BeePixmapItem(QtGui.QImage(), self.filename)
        item._orig_width = self._orig_width
        item._orig_height = self._orig_height
        item._exif_trans = self._exif_trans
        item._img_format = self._img_format
        item._source_path = self._source_path
        item._source_bytes = self._source_bytes
        item._bee_source = self._bee_source
        item.thumb_pixmap = QtGui.QPixmap(self.thumb_pixmap)
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        if self.flip() == -1:
            item.do_flip()
        item.crop = QtCore.QRectF(self.crop)
        item.setOpacity(self.opacity())
        item.grayscale = self.grayscale
        item.custom_title = self.custom_title
        item.note = self.note
        item.palette_hex = list(self.palette_hex)
        item.created_ts = self.created_ts
        return item

    @cached_property
    def color_gamut(self):
        logger.debug(f'Calculating color gamut for {self}')
        gamut = defaultdict(int)
        # Sampling from Tier-1 / Tier-0 image is already <= 1280px and accurate!
        img = self.decode_source_qimage(max_edge=1000)
        step = max(1, int(max(img.width(), img.height()) / 1000))

        for i in range(0, img.width(), step):
            for j in range(0, img.height(), step):
                rgb = img.pixelColor(i, j)
                rgbtuple = (rgb.red(), rgb.blue(), rgb.green())
                if (5 < rgb.alpha()
                        and min(rgbtuple) < 250 and max(rgbtuple) > 5):
                    gamut[rgb.hue(), rgb.saturation()] += 1

        logger.debug(f'Got {len(gamut)} color gamut values')
        return gamut

    def copy_to_clipboard(self, clipboard):
        clipboard.setPixmap(self.pixmap())

    def reset_crop(self):
        self.crop = QtCore.QRectF(
            0, 0, self._orig_width, self._orig_height)

    @property
    def crop_handle_size(self):
        return self.fixed_length_for_viewport(self.CROP_HANDLE_SIZE)

    def crop_handle_topleft(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x(),
            topleft.y(),
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_bottomleft(self):
        bottomleft = self.crop_temp.bottomLeft()
        return QtCore.QRectF(
            bottomleft.x(),
            bottomleft.y() - self.crop_handle_size,
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_bottomright(self):
        bottomright = self.crop_temp.bottomRight()
        return QtCore.QRectF(
            bottomright.x() - self.crop_handle_size,
            bottomright.y() - self.crop_handle_size,
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handle_topright(self):
        topright = self.crop_temp.topRight()
        return QtCore.QRectF(
            topright.x() - self.crop_handle_size,
            topright.y(),
            self.crop_handle_size,
            self.crop_handle_size)

    def crop_handles(self):
        return (self.crop_handle_topleft,
                self.crop_handle_bottomleft,
                self.crop_handle_bottomright,
                self.crop_handle_topright)

    def crop_edge_top(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x() + self.crop_handle_size,
            topleft.y(),
            self.crop_temp.width() - 2 * self.crop_handle_size,
            self.crop_handle_size)

    def crop_edge_left(self):
        topleft = self.crop_temp.topLeft()
        return QtCore.QRectF(
            topleft.x(),
            topleft.y() + self.crop_handle_size,
            self.crop_handle_size,
            self.crop_temp.height() - 2 * self.crop_handle_size)

    def crop_edge_bottom(self):
        bottomleft = self.crop_temp.bottomLeft()
        return QtCore.QRectF(
            bottomleft.x() + self.crop_handle_size,
            bottomleft.y() - self.crop_handle_size,
            self.crop_temp.width() - 2 * self.crop_handle_size,
            self.crop_handle_size)

    def crop_edge_right(self):
        topright = self.crop_temp.topRight()
        return QtCore.QRectF(
            topright.x() - self.crop_handle_size,
            topright.y() + self.crop_handle_size,
            self.crop_handle_size,
            self.crop_temp.height() - 2 * self.crop_handle_size)

    def crop_edges(self):
        return (self.crop_edge_top,
                self.crop_edge_left,
                self.crop_edge_bottom,
                self.crop_edge_right)

    def get_crop_handle_cursor(self, handle):
        """Gets the crop cursor for the given handle."""

        is_topleft_or_bottomright = handle in (
            self.crop_handle_topleft, self.crop_handle_bottomright)
        return self.get_diag_cursor(is_topleft_or_bottomright)

    def get_crop_edge_cursor(self, edge):
        """Gets the crop edge cursor for the given edge."""

        top_or_bottom = edge in (
            self.crop_edge_top, self.crop_edge_bottom)
        sideways = (45 < self.rotation() < 135
                    or 225 < self.rotation() < 315)

        if top_or_bottom is sideways:
            return Qt.CursorShape.SizeHorCursor
        else:
            return Qt.CursorShape.SizeVerCursor

    def draw_crop_rect(self, painter, rect):
        """Paint a dotted rectangle for the cropping UI."""
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
        pen.setWidth(2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(rect)
        pen.setColor(QtGui.QColor(0, 0, 0))
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawRect(rect)

    def _select_render_pixmap(self, painter, widget) -> QtGui.QPixmap:
        if self._orig_width <= 0 or self._orig_height <= 0:
            return self.thumb_pixmap

        ct = painter.combinedTransform()
        # Rotation-invariant Euclidean device scale
        item_to_device = math.hypot(ct.m11(), ct.m12())
        screen_max_edge = self.max_orig_edge * item_to_device

        if screen_max_edge <= LOD_THUMB_MAX:
            tier = 0
        elif screen_max_edge <= LOD_MID_MAX:
            tier = 1
        else:
            tier = 2

        is_offscreen_export = (widget is None)
        pm = LODCacheManager.instance().get_best_pixmap(
            self, desired_tier=tier, sync_if_missing=is_offscreen_export)

        if self.grayscale:
            pm = self._to_grayscale_pixmap(pm)
        return pm

    def paint(self, painter, option, widget):
        if self._orig_width <= 0 or self._orig_height <= 0:
            return

        ct = painter.combinedTransform()
        item_to_device = math.hypot(ct.m11(), ct.m12())
        dpr = max(1.0, float(painter.device().devicePixelRatioF())) if painter.device() else 1.0
        item_to_logical = item_to_device / dpr
        screen_max_edge = self.max_orig_edge * item_to_logical
        if item_to_device < 2.0:
            painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform)

        pm = self._select_render_pixmap(painter, widget)
        if pm.isNull():
            return

        if self.crop_mode:
            self.paint_debug(painter, option, widget)

            full_target = QtCore.QRectF(0, 0, self._orig_width, self._orig_height)
            full_src = QtCore.QRectF(0, 0, pm.width(), pm.height())
            painter.drawPixmap(full_target, pm, full_src)

            path = QtGui.QPainterPath()
            path.addRect(full_target)
            path.addRect(self.crop_temp)
            color = QtGui.QColor(0, 0, 0)
            color.setAlpha(100)
            painter.setBrush(QtGui.QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)
            painter.setBrush(QtGui.QBrush())

            for handle in self.crop_handles():
                self.draw_crop_rect(painter, handle())
            self.draw_crop_rect(painter, self.crop_temp)
        else:
            px_unit = 1.0 / max(0.03, item_to_logical)
            crop_max = max(self.crop.width(), self.crop.height())
            pad = max(18.0, 0.045 * crop_max)

            has_raster_target = (
                widget is not None
                or isinstance(painter.device(), (QtGui.QPixmap, QtGui.QImage))
            )
            if has_raster_target and screen_max_edge > 90 and self.opacity() > 0.80:
                # Silky-smooth 9-patch Gaussian drop shadow (LOD-gated for 1000+ image speed)
                _draw_soft_card_shadow(
                    painter,
                    self.crop,
                    px_unit,
                    is_dark=(constants.ACTIVE_THEME == 'dark'),
                )

            did_hover_tx = False
            if abs(self._hover_lift) > 1e-3 and screen_max_edge > 45.0:
                sc = self.scene()
                is_underlay = bool(
                    self.stack_id
                    and not self.is_stack_cover
                    and sc is not None
                    and hasattr(sc, 'stack_manager')
                    and sc.stack_manager.active_spread_stack_id != self.stack_id
                )
                base_px = 3.2 if is_underlay else 4.6
                max_frac = 0.013 if is_underlay else 0.018
                raw_lift_frac = min(max_frac, max(0.008, base_px / max(60.0, screen_max_edge))) * self._hover_lift
                max_safe_frac = (pad * 0.35) / max(1.0, crop_max * 0.5)
                lift_frac = max(-max_safe_frac, min(max_safe_frac, raw_lift_frac))
                max_dy = pad * 0.25
                lift_dy = max(-max_dy, min(max_dy, min(1.1 * px_unit, max_dy) * self._hover_lift))
                c = self.crop.center()
                painter.save()
                did_hover_tx = True
                painter.translate(c.x(), c.y() - lift_dy)
                painter.scale(1.0 + lift_frac, 1.0 + lift_frac)
                painter.translate(-c.x(), -c.y())

            if pm.width() == self._orig_width and pm.height() == self._orig_height:
                src_rect = self.crop
            else:
                sx = pm.width() / self._orig_width
                sy = pm.height() / self._orig_height
                src_rect = QtCore.QRectF(
                    self.crop.x() * sx,
                    self.crop.y() * sy,
                    self.crop.width() * sx,
                    self.crop.height() * sy,
                )
            painter.drawPixmap(self.crop, pm, src_rect)
            if did_hover_tx:
                painter.restore()
            self._paint_stack_overlays(painter, item_to_device)
            self.paint_selectable(painter, option, widget)

    def _paint_stack_overlays(self, painter: QtGui.QPainter, item_to_device: float):
        if not self.stack_id or item_to_device <= 1e-5:
            return
        dpr = max(1.0, float(painter.device().devicePixelRatioF())) if painter.device() else 1.0
        item_to_logical = item_to_device / dpr
        if item_to_logical <= 1e-5:
            return
        sc = self.scene()
        is_spread = (
            sc is not None
            and hasattr(sc, 'stack_manager')
            and sc.stack_manager.active_spread_stack_id == self.stack_id
        )

        # Spread Mode only: Cover Radio-Check Badge at top-left of card
        # (Collapsed [N] count and group name are painted by StackOverlayLabelItem)
        if is_spread and (self.is_stack_cover or self._hover_inside):
            painter.save()
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            px_unit = 1.0 / item_to_logical
            diam = 24.0 * px_unit
            pad = 10.0 * px_unit
            cx = self.crop.left() + pad + diam * 0.5
            cy = self.crop.top() + pad + diam * 0.5
            painter.translate(cx, cy)
            painter.scale(px_unit, px_unit)

            r_local = QtCore.QRectF(-12.0, -12.0, 24.0, 24.0)
            if self.is_stack_cover:
                painter.setBrush(QtGui.QColor('#FFDA12'))
                painter.setPen(QtGui.QPen(QtGui.QColor('#E5C100'), 1.5))
                painter.drawEllipse(r_local)
                ck = QtGui.QPen(QtGui.QColor('#1A1A1C'), 2.1)
            else:
                painter.setBrush(QtGui.QColor(255, 255, 255, 215))
                painter.setPen(QtGui.QPen(QtGui.QColor(26, 26, 28, 90), 1.3))
                painter.drawEllipse(r_local)
                ck = QtGui.QPen(QtGui.QColor(26, 26, 28, 120), 1.8)

            ck.setCapStyle(Qt.PenCapStyle.RoundCap)
            ck.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(ck)
            painter.drawLine(QtCore.QPointF(-4.5, 0.3), QtCore.QPointF(-1.2, 3.6))
            painter.drawLine(QtCore.QPointF(-1.2, 3.6), QtCore.QPointF(4.8, -3.2))
            painter.restore()

    def enter_crop_mode(self):
        logger.debug(f'Entering crop mode on {self}')
        self.prepareGeometryChange()
        self.crop_mode = True
        self.crop_temp = QtCore.QRectF(self.crop)
        self.crop_mode_move = None
        self.crop_mode_event_start = None
        self.grabKeyboard()
        self.update()
        self.scene().crop_item = self

    def exit_crop_mode(self, confirm):
        logger.debug(f'Exiting crop mode with {confirm} on {self}')
        if confirm and self.crop != self.crop_temp:
            self.scene().undo_stack.push(
                commands.CropItem(self, self.crop_temp))
        self.prepareGeometryChange()
        self.crop_mode = False
        self.crop_temp = None
        self.crop_mode_move = None
        self.crop_mode_event_start = None
        self.ungrabKeyboard()
        self.update()
        self.scene().crop_item = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.exit_crop_mode(confirm=True)
        elif event.key() == Qt.Key.Key_Escape:
            self.exit_crop_mode(confirm=False)
        else:
            super().keyPressEvent(event)

    def hoverEnterEvent(self, event):
        self._hover_inside = True
        sc = self.scene()
        if sc is not None and hasattr(sc, 'on_item_hover_changed'):
            sc.on_item_hover_changed(self, True)
        if self.stack_id:
            self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if self._hover_inside:
            self._hover_inside = False
            sc = self.scene()
            if sc is not None and hasattr(sc, 'on_item_hover_changed'):
                sc.on_item_hover_changed(self, False)
            if self.stack_id:
                self.update()
        super().hoverLeaveEvent(event)

    def hoverMoveEvent(self, event):
        if not self.crop_mode:
            return super().hoverMoveEvent(event)

        for handle in self.crop_handles():
            if handle().contains(event.pos()):
                self.set_cursor(self.get_crop_handle_cursor(handle))
                return
        for edge in self.crop_edges():
            if edge().contains(event.pos()):
                self.set_cursor(self.get_crop_edge_cursor(edge))
                return
        self.unset_cursor()

    def mousePressEvent(self, event):
        if not self.crop_mode:
            return super().mousePressEvent(event)

        event.accept()
        for handle in self.crop_handles():
            if handle().contains(event.pos()):
                self.crop_mode_event_start = event.pos()
                self.crop_mode_move = handle
                return
        for edge in self.crop_edges():
            if edge().contains(event.pos()):
                self.crop_mode_event_start = event.pos()
                self.crop_mode_move = edge
                return
        self.exit_crop_mode(
            confirm=self.crop_temp.contains(event.pos()))

    def ensure_point_within_crop_bounds(self, point, handle):
        """Returns the point, or the nearest point within the pixmap."""
        w = self._orig_width
        h = self._orig_height

        if handle == self.crop_handle_topleft:
            topleft = QtCore.QPointF(0, 0)
            bottomright = self.crop_temp.bottomRight()
        if handle == self.crop_handle_bottomleft:
            topleft = QtCore.QPointF(0, self.crop_temp.top())
            bottomright = QtCore.QPointF(self.crop_temp.right(), h)
        if handle == self.crop_handle_bottomright:
            topleft = self.crop_temp.topLeft()
            bottomright = QtCore.QPointF(w, h)
        if handle == self.crop_handle_topright:
            topleft = QtCore.QPointF(self.crop_temp.left(), 0)
            bottomright = QtCore.QPointF(w, self.crop_temp.bottom())
        if handle == self.crop_edge_top:
            topleft = QtCore.QPointF(0, 0)
            bottomright = QtCore.QPointF(w, self.crop_temp.bottom())
        if handle == self.crop_edge_bottom:
            topleft = QtCore.QPointF(0, self.crop_temp.top())
            bottomright = QtCore.QPointF(w, h)
        if handle == self.crop_edge_left:
            topleft = QtCore.QPointF(0, 0)
            bottomright = QtCore.QPointF(self.crop_temp.right(), h)
        if handle == self.crop_edge_right:
            topleft = QtCore.QPointF(self.crop_temp.left(), 0)
            bottomright = QtCore.QPointF(w, h)

        point.setX(min(bottomright.x(), max(topleft.x(), point.x())))
        point.setY(min(bottomright.y(), max(topleft.y(), point.y())))

        return point

    def mouseMoveEvent(self, event):
        if self.crop_mode and self.crop_mode_event_start:
            diff = event.pos() - self.crop_mode_event_start
            if self.crop_mode_move == self.crop_handle_topleft:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setTopLeft(new)
            if self.crop_mode_move == self.crop_handle_bottomleft:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomLeft() + diff, self.crop_mode_move)
                self.crop_temp.setBottomLeft(new)
            if self.crop_mode_move == self.crop_handle_bottomright:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomRight() + diff, self.crop_mode_move)
                self.crop_temp.setBottomRight(new)
            if self.crop_mode_move == self.crop_handle_topright:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topRight() + diff, self.crop_mode_move)
                self.crop_temp.setTopRight(new)
            if self.crop_mode_move == self.crop_edge_top:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setTop(new.y())
            if self.crop_mode_move == self.crop_edge_left:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topLeft() + diff, self.crop_mode_move)
                self.crop_temp.setLeft(new.x())
            if self.crop_mode_move == self.crop_edge_bottom:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.bottomLeft() + diff, self.crop_mode_move)
                self.crop_temp.setBottom(new.y())
            if self.crop_mode_move == self.crop_edge_right:
                new = self.ensure_point_within_crop_bounds(
                    self.crop_temp.topRight() + diff, self.crop_mode_move)
                self.crop_temp.setRight(new.x())
            self.update()
            self.crop_mode_event_start = event.pos()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.crop_mode:
            self.crop_mode_move = None
            self.crop_mode_event_start = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)


@register_item
class BeeTextItem(BeeItemMixin, QtWidgets.QGraphicsTextItem):
    """Class for text added by the user."""

    TYPE = 'text'

    def __init__(self, text=None, **kwargs):
        super().__init__(text or "Text")
        self.save_id = None
        logger.debug(f'Initialized {self}')
        self.is_image = False
        self.init_selectable()
        self.is_editable = True
        self.edit_mode = False
        self.setDefaultTextColor(QtGui.QColor(*COLORS['Scene:Text']))

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        item = cls(**data)
        return item

    def __str__(self):
        txt = self.toPlainText()[:40]
        return (f'Text "{txt}"')

    def get_extra_save_data(self):
        return {'text': self.toPlainText()}

    def contains(self, point):
        return self.bounding_rect_unselected().contains(point)

    def paint(self, painter, option, widget):
        painter.setPen(Qt.PenStyle.NoPen)
        color = QtGui.QColor(0, 0, 0)
        color.setAlpha(40)
        brush = QtGui.QBrush(color)
        painter.setBrush(brush)
        painter.drawRect(QtWidgets.QGraphicsTextItem.boundingRect(self))
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        super().paint(painter, option, widget)
        self.paint_selectable(painter, option, widget)

    def create_copy(self):
        item = BeeTextItem(self.toPlainText())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        if self.flip() == -1:
            item.do_flip()
        return item

    def enter_edit_mode(self):
        logger.debug(f'Entering edit mode on {self}')
        self.edit_mode = True
        self.old_text = self.toPlainText()
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction)
        self.scene().edit_item = self

    def exit_edit_mode(self, commit=True):
        logger.debug(f'Exiting edit mode on {self}')
        self.edit_mode = False
        self.setTextCursor(QtGui.QTextCursor(self.document()))
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.scene().edit_item = None
        if commit:
            self.scene().undo_stack.push(
                commands.ChangeText(self, self.toPlainText(), self.old_text))
            if not self.toPlainText().strip():
                logger.debug('Removing empty text item')
                self.scene().undo_stack.push(
                    commands.DeleteItems(self.scene(), [self]))
        else:
            self.setPlainText(self.old_text)

    def has_selection_handles(self):
        return super().has_selection_handles() and not self.edit_mode

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return)
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.exit_edit_mode()
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Escape
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.exit_edit_mode(commit=False)
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_to_clipboard(self, clipboard):
        clipboard.setText(self.toPlainText())


@register_item
class BeeErrorItem(BeeItemMixin, QtWidgets.QGraphicsTextItem):
    """Class for displaying error messages when an item can't be loaded
    from a bee file.
    """

    TYPE = 'error'

    def __init__(self, text=None, **kwargs):
        super().__init__(text or "Text")
        self.original_save_id = None
        logger.debug(f'Initialized {self}')
        self.is_image = False
        self.init_selectable()
        self.is_editable = False
        self.setDefaultTextColor(QtGui.QColor(*COLORS['Scene:Text']))

    @classmethod
    def create_from_data(cls, **kwargs):
        data = kwargs.get('data', {})
        item = cls(**data)
        return item

    def __str__(self):
        txt = self.toPlainText()[:40]
        return (f'Error "{txt}"')

    def contains(self, point):
        return self.bounding_rect_unselected().contains(point)

    def paint(self, painter, option, widget):
        painter.setPen(Qt.PenStyle.NoPen)
        color = QtGui.QColor(200, 0, 0)
        brush = QtGui.QBrush(color)
        painter.setBrush(brush)
        painter.drawRect(QtWidgets.QGraphicsTextItem.boundingRect(self))
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        super().paint(painter, option, widget)
        self.paint_selectable(painter, option, widget)

    def update_from_data(self, **kwargs):
        self.original_save_id = kwargs.get('save_id', self.original_save_id)
        self.setPos(kwargs.get('x', self.pos().x()),
                    kwargs.get('y', self.pos().y()))
        self.setZValue(kwargs.get('z', self.zValue()))
        self.setScale(kwargs.get('scale', self.scale()))
        self.setRotation(kwargs.get('rotation', self.rotation()))

    def create_copy(self):
        item = BeeErrorItem(self.toPlainText())
        item.setPos(self.pos())
        item.setZValue(self.zValue())
        item.setScale(self.scale())
        item.setRotation(self.rotation())
        return item

    def flip(self, *args, **kwargs):
        return 1

    def do_flip(self, *args, **kwargs):
        pass

    def copy_to_clipboard(self, clipboard):
        clipboard.setText(self.toPlainText())
