# This file is part of Birdboard (GPL-3.0-or-later).

"""Deskboard Inverted Contextual Bottom Toolbar & Toast Notification."""

from dataclasses import dataclass
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import constants
from beeref.assets import BeeAssets
from beeref.deskboard_motion import SPRING_PRESENT, SPRING_SOFT, SPRING_TOAST


TOOLBAR_HEIGHT = 58
TOOLBAR_RADIUS = 23.0
SLOT_PITCH = 62
BTN_W = 56
BTN_H = 44
BTN_RADIUS = 14.0
BOTTOM_MARGIN = 32
SHADOW_PAD_X = 28
SHADOW_PAD_TOP = 38    # Space for tooltip above toolbar
SHADOW_PAD_BOT = 34

_PILL_SHADOW_CACHE: dict[tuple, QtGui.QPixmap] = {}


def _get_smooth_pill_shadow(
    pill_w: int,
    pill_h: int,
    radius: float,
    pad: int,
    blur_radius: float,
    y_offset: float,
    alpha: int,
    dpr: float,
) -> QtGui.QPixmap:
    """Render & cache a true ring-free C++ Gaussian drop shadow for a rounded pill."""
    key = (pill_w, pill_h, round(radius, 1), pad, round(blur_radius, 1), round(y_offset, 1), alpha, round(dpr, 2))
    cached = _PILL_SHADOW_CACHE.get(key)
    if cached is not None:
        return cached

    tot_w = pill_w + pad * 2
    tot_h = pill_h + pad * 2
    src_pm = QtGui.QPixmap(tot_w, tot_h)
    src_pm.fill(Qt.GlobalColor.transparent)

    sp = QtGui.QPainter(src_pm)
    sp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    sp.setPen(Qt.PenStyle.NoPen)
    sp.setBrush(QtGui.QColor(0, 0, 0, alpha))
    sp.drawRoundedRect(
        QtCore.QRectF(float(pad), float(pad) + y_offset, float(pill_w), float(pill_h)),
        radius,
        radius,
    )
    sp.end()

    scene = QtWidgets.QGraphicsScene(0.0, 0.0, float(tot_w), float(tot_h))
    item = QtWidgets.QGraphicsPixmapItem(src_pm)
    blur = QtWidgets.QGraphicsBlurEffect()
    blur.setBlurRadius(blur_radius)
    blur.setBlurHints(QtWidgets.QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(blur)
    scene.addItem(item)

    img_1x = QtGui.QImage(tot_w, tot_h, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img_1x.fill(Qt.GlobalColor.transparent)
    op = QtGui.QPainter(img_1x)
    op.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    scene.render(
        op,
        QtCore.QRectF(0.0, 0.0, float(tot_w), float(tot_h)),
        QtCore.QRectF(0.0, 0.0, float(tot_w), float(tot_h)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
    )
    op.end()

    hi_img = img_1x.scaled(
        max(1, round(tot_w * dpr)),
        max(1, round(tot_h * dpr)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out_pm = QtGui.QPixmap.fromImage(hi_img)
    out_pm.setDevicePixelRatio(dpr)

    if len(_PILL_SHADOW_CACHE) > 48:
        _PILL_SHADOW_CACHE.clear()
    _PILL_SHADOW_CACHE[key] = out_pm
    return out_pm


@dataclass
class ToolbarButtonSpec:
    id: str
    icon: str
    tooltip: str
    enabled: bool = True


class DeskboardToast(QtWidgets.QWidget):
    """Floating pill toast above the bottom toolbar (`bottom ≈ 104px`)."""

    _current: 'DeskboardToast | None' = None

    @classmethod
    def show_toast(cls, parent: QtWidgets.QWidget, text: str, duration_ms: int = 1650):
        if cls._current is not None:
            try:
                cls._current.hide()
                cls._current.deleteLater()
            except RuntimeError:
                pass
            cls._current = None

        toast = cls(parent, text, duration_ms)
        cls._current = toast

    def __init__(self, parent: QtWidgets.QWidget, text: str, duration_ms: int):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.text = text
        self.font_ui = BeeAssets().font(13, 600)
        fm = QtGui.QFontMetrics(self.font_ui)
        self.pill_w = max(140, fm.horizontalAdvance(text) + 38)
        self.pill_h = 42
        self.pad = 16
        self.setFixedSize(self.pill_w + self.pad * 2, self.pill_h + self.pad * 2)

        self._start_t = time.perf_counter()
        self._phase = 'in'
        self._hold_ms = duration_ms
        self._fade_start = 0.0
        self._alpha = 0.0
        self._y_offset = 36.0

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)

        self._reposition()
        self.show()
        self.raise_()
        self._timer.start()

    def _reposition(self):
        p = self.parentWidget()
        if p is None:
            return
        x = (p.width() - self.width()) // 2
        base_y = p.height() - 104 - self.pill_h - self.pad
        self.move(x, round(base_y + self._y_offset))

    def _tick(self):
        now = time.perf_counter()
        if self._phase == 'in':
            dt = now - self._start_t
            prog = SPRING_TOAST.value(dt)
            self._y_offset = 36.0 * (1.0 - prog)
            self._alpha = min(1.0, dt / 0.14)
            self._reposition()
            self.update()
            if dt >= SPRING_TOAST.settle_duration:
                self._phase = 'hold'
                self._y_offset = 0.0
                self._alpha = 1.0
                QtCore.QTimer.singleShot(self._hold_ms, self._begin_fade)
        elif self._phase == 'out':
            dt = now - self._fade_start
            t = min(1.0, dt / 0.22)
            self._alpha = 1.0 - t
            self._y_offset = 8.0 * t
            self._reposition()
            self.update()
            if t >= 1.0:
                self._timer.stop()
                self.hide()
                if DeskboardToast._current is self:
                    DeskboardToast._current = None
                self.deleteLater()

    def _begin_fade(self):
        if not self.isVisible():
            return
        self._phase = 'out'
        self._fade_start = time.perf_counter()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self._alpha)))

        is_dark = (constants.ACTIVE_THEME == 'dark')
        bg = QtGui.QColor('#F5F6F7') if is_dark else QtGui.QColor('#16181A')
        fg = QtGui.QColor('#16181A') if is_dark else QtGui.QColor('#F5F6F7')

        rect = QtCore.QRectF(self.pad, self.pad, self.pill_w, self.pill_h)
        dpr = self.devicePixelRatioF()
        sh_pm = _get_smooth_pill_shadow(
            self.pill_w, self.pill_h, self.pill_h * 0.5,
            pad=self.pad, blur_radius=12.0, y_offset=4.0, alpha=82, dpr=dpr,
        )
        p.drawPixmap(0, 0, sh_pm)

        p.setBrush(bg)
        rim = QtGui.QColor(fg)
        rim.setAlpha(30)
        p.setPen(QtGui.QPen(rim, 1.0))
        p.drawRoundedRect(rect, self.pill_h * 0.5, self.pill_h * 0.5)

        p.setFont(self.font_ui)
        p.setPen(fg)
        p.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignCenter),
            self.text,
        )
        p.end()


class ContextualToolbar(QtWidgets.QWidget):
    """Inverted floating action bar anchored 32px above bottom center."""

    action_triggered = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget, force_dark_bg: bool = False):
        super().__init__(parent)
        self.force_dark_bg = force_dark_bg
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self.buttons: list[ToolbarButtonSpec] = []
        self.hovered_idx: int = -1
        self._pressed_idx: int = -1
        self._shown_logical: bool = False

        # Animated state
        self._y_slide = 80.0          # 80 -> 0 on SPRING_PRESENT
        self._slide_from = 80.0
        self._slide_to = 80.0
        self._slide_t0 = 0.0

        self._cur_pill_w = 268.0
        self._w_from = 268.0
        self._w_to = 268.0
        self._w_t0 = 0.0

        self._anim_timer = QtCore.QTimer(self)
        self._anim_timer.setInterval(8)  # 120 FPS
        self._anim_timer.timeout.connect(self._on_tick)

        self.font_tip = BeeAssets().font(12, 600)
        self.hide()

    def set_buttons(self, specs: list[ToolbarButtonSpec], visible: bool = True):
        if not visible or not specs:
            if self._shown_logical:
                self._shown_logical = False
                self.hovered_idx = -1
                self._slide_from = self._y_slide
                self._slide_to = 115.0
                self._slide_t0 = time.perf_counter()
                self._anim_timer.start()
            return

        target_w = float(len(specs) * SLOT_PITCH + 20)
        same_ids = [b.id for b in self.buttons] == [b.id for b in specs]
        self.buttons = list(specs)

        if not self._shown_logical:
            self._shown_logical = True
            self._cur_pill_w = target_w
            self._w_from = target_w
            self._w_to = target_w
            self._slide_from = max(64.0, self._y_slide)
            self._slide_to = 0.0
            self._slide_t0 = time.perf_counter()
            self._sync_geometry()
            self.show()
            self.raise_()
            self._anim_timer.start()
        else:
            if abs(target_w - self._w_to) > 0.5:
                self._w_from = self._cur_pill_w
                self._w_to = target_w
                self._w_t0 = time.perf_counter()
                self._anim_timer.start()
            elif not same_ids:
                self.update()
            self._sync_geometry()
            self.raise_()

    def sync_parent_resize(self):
        if self.isVisible():
            self._sync_geometry()

    def _sync_geometry(self):
        p = self.parentWidget()
        if p is None:
            return
        max_w = round(max(self._cur_pill_w, self._w_to)) + SHADOW_PAD_X * 2 + 80
        total_h = TOOLBAR_HEIGHT + SHADOW_PAD_TOP + SHADOW_PAD_BOT
        self.setFixedSize(max_w, total_h)
        x = (p.width() - max_w) // 2
        y = p.height() - BOTTOM_MARGIN - TOOLBAR_HEIGHT - SHADOW_PAD_TOP + round(self._y_slide)
        self.move(x, y)

    def _on_tick(self):
        now = time.perf_counter()
        still_running = False

        # Slide spring
        if abs(self._y_slide - self._slide_to) > 0.15 or (now - self._slide_t0) < 0.05:
            dt = now - self._slide_t0
            if self._slide_to > 50.0:
                # Quick clean dismissal
                prog = min(1.0, dt / 0.20)
                prog = prog * prog
            else:
                prog = SPRING_PRESENT.value(dt)
                if dt >= SPRING_PRESENT.settle_duration:
                    prog = 1.0
            self._y_slide = self._slide_from + (self._slide_to - self._slide_from) * prog
            if prog < 1.0:
                still_running = True
            else:
                self._y_slide = self._slide_to

        # Width morph spring
        if abs(self._cur_pill_w - self._w_to) > 0.2:
            dt_w = now - self._w_t0
            prog_w = SPRING_SOFT.value(dt_w)
            if dt_w >= SPRING_SOFT.settle_duration:
                prog_w = 1.0
            self._cur_pill_w = self._w_from + (self._w_to - self._w_from) * prog_w
            if prog_w < 1.0:
                still_running = True
            else:
                self._cur_pill_w = self._w_to

        self._sync_geometry()
        self.update()

        if not still_running:
            self._anim_timer.stop()
            if not self._shown_logical and self._y_slide >= 80.0:
                self.hide()

    def _pill_rect(self) -> QtCore.QRectF:
        px = (self.width() - self._cur_pill_w) * 0.5
        py = float(SHADOW_PAD_TOP)
        return QtCore.QRectF(px, py, self._cur_pill_w, float(TOOLBAR_HEIGHT))

    def _slot_rect(self, idx: int) -> QtCore.QRectF:
        pr = self._pill_rect()
        total_slots_w = len(self.buttons) * SLOT_PITCH
        start_x = pr.center().x() - total_slots_w * 0.5 + (SLOT_PITCH - BTN_W) * 0.5
        sx = start_x + idx * SLOT_PITCH
        sy = pr.top() + (TOOLBAR_HEIGHT - BTN_H) * 0.5
        return QtCore.QRectF(sx, sy, float(BTN_W), float(BTN_H))

    def _slot_at(self, pos: QtCore.QPointF) -> int:
        if not self._pill_rect().contains(pos):
            return -1
        for i in range(len(self.buttons)):
            if self._slot_rect(i).contains(pos):
                return i
        return -1

    def leaveEvent(self, event):
        if self.hovered_idx != -1 or self._pressed_idx != -1:
            self.hovered_idx = -1
            self._pressed_idx = -1
            self.unsetCursor()
            self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        idx = self._slot_at(event.position())
        if idx != self.hovered_idx:
            self.hovered_idx = idx
            if idx >= 0 and self.buttons[idx].enabled:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
            self.update()
        if self._pill_rect().contains(event.position()):
            event.accept()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._slot_at(event.position())
            if idx >= 0:
                if self.buttons[idx].enabled:
                    self._pressed_idx = idx
                    self.update()
                event.accept()
                return
            if self._pill_rect().contains(event.position()):
                event.accept()
                return
        event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_idx >= 0:
            idx = self._slot_at(event.position())
            pressed = self._pressed_idx
            self._pressed_idx = -1
            self.update()
            if idx == pressed and 0 <= idx < len(self.buttons) and self.buttons[idx].enabled:
                self.action_triggered.emit(self.buttons[idx].id)
            event.accept()
            return
        event.ignore()

    def paintEvent(self, event):
        if not self.buttons:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)

        invert_light = (not self.force_dark_bg) and (constants.ACTIVE_THEME == 'dark')
        if invert_light:
            bg = QtGui.QColor('#F5F6F7')
            fg = QtGui.QColor('#16181A')
            hover_fill = QtGui.QColor(22, 24, 26, 24)
            rim_col = QtGui.QColor(22, 24, 26, 30)
        else:
            bg = QtGui.QColor('#16181A')
            fg = QtGui.QColor('#F5F6F7')
            hover_fill = QtGui.QColor(245, 246, 247, 28)
            rim_col = QtGui.QColor(245, 246, 247, 32)

        pr = self._pill_rect()

        # Silky-smooth Gaussian ambient toolbar shadow (ring-free!)
        sh_pad = 30
        sh_pm = _get_smooth_pill_shadow(
            max(40, round(pr.width())),
            TOOLBAR_HEIGHT,
            TOOLBAR_RADIUS,
            pad=sh_pad,
            blur_radius=19.0,
            y_offset=8.0,
            alpha=96,
            dpr=self.devicePixelRatioF(),
        )
        p.drawPixmap(
            QtCore.QPointF(pr.left() - sh_pad, pr.top() - sh_pad),
            sh_pm,
        )

        # Main pill body
        p.setBrush(bg)
        p.setPen(QtGui.QPen(rim_col, 1.0))
        p.drawRoundedRect(pr, TOOLBAR_RADIUS, TOOLBAR_RADIUS)

        # Clip slots inside pill while morphing width
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(pr, TOOLBAR_RADIUS, TOOLBAR_RADIUS)
        p.save()
        p.setClipPath(clip)

        assets = BeeAssets()
        for i, b in enumerate(self.buttons):
            sr = self._slot_rect(i)
            is_hov = (i == self.hovered_idx and b.enabled)
            is_prs = (i == self._pressed_idx and b.enabled)

            if is_hov:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(hover_fill)
                p.drawRoundedRect(sr, BTN_RADIUS, BTN_RADIUS)

            icon_sz = 19
            opacity = 1.0 if b.enabled else 0.28
            pm = assets.svg_icon_pixmap(b.icon, size=icon_sz, color=fg, opacity=opacity)
            cx = sr.center().x()
            cy = sr.center().y()
            p.save()
            p.translate(cx, cy)
            if is_prs:
                p.scale(0.92, 0.92)
            elif is_hov:
                p.scale(1.08, 1.08)
            p.drawPixmap(
                QtCore.QPointF(-icon_sz * 0.5, -icon_sz * 0.5),
                pm,
            )
            p.restore()

        p.restore()

        # Floating Tooltip above hovered button
        if 0 <= self.hovered_idx < len(self.buttons):
            b = self.buttons[self.hovered_idx]
            if b.tooltip:
                sr = self._slot_rect(self.hovered_idx)
                fm = QtGui.QFontMetrics(self.font_tip)
                tw = fm.horizontalAdvance(b.tooltip) + 20
                th = 26.0
                tx = max(4.0, min(self.width() - tw - 4.0, sr.center().x() - tw * 0.5))
                ty = pr.top() - th - 8.0
                tip_rect = QtCore.QRectF(tx, ty, float(tw), th)
                p.setPen(QtGui.QPen(rim_col, 1.0))
                p.setBrush(bg)
                p.drawRoundedRect(tip_rect, 8.0, 8.0)
                p.setFont(self.font_tip)
                tip_fg = QtGui.QColor(fg)
                if not b.enabled:
                    tip_fg.setAlpha(170)
                p.setPen(tip_fg)
                p.drawText(tip_rect, int(Qt.AlignmentFlag.AlignCenter), b.tooltip)

        p.end()
