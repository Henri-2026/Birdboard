# This file is part of Birdboard.
#
# Birdboard is free software under the GNU General Public License v3.0+.

"""Penart Frosted Glass Dropdown & Submenu System (`penart-ui-craft` spec).

Implements:
  * Dark Frosted Glass surface: rgba(28, 28, 34, 0.84) + 20px backdrop blur
    & 150% saturation boost + 1px specular hairline rim rgba(255,255,255,0.16)
    + 1px top inset highlight rgba(255,255,255,0.12).
  * High-contrast typography: #F2F2F7 primary, #9A9AA2 shortcut/arrow,
    #6C6C74 disabled, #3A82F7 active checkmark.
  * Concentric Corner Radius: R_outer = 11px, Padding = 5px, R_inner = 6px.
  * Dropdown Inertia Unfurl physics: 480ms, cubic-bezier(0.16, 1, 0.3, 1),
    3-keyframe trajectory from top-left origin at 120 FPS.
"""

from dataclasses import dataclass
import math
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt


# --- Penart UI Tokens ---
BG_GLASS_TINT = QtGui.QColor(28, 28, 34, 214)        # rgba(28, 28, 34, 0.84)
RIM_OUTER = QtGui.QColor(255, 255, 255, 41)          # rgba(255, 255, 255, 0.16)
RIM_TOP_INSET = QtGui.QColor(255, 255, 255, 31)      # rgba(255, 255, 255, 0.12)
RIM_SEPARATOR = QtGui.QColor(255, 255, 255, 21)      # rgba(255, 255, 255, 0.08)

HOVER_BG = QtGui.QColor(255, 255, 255, 28)           # Soft frosted highlight
HOVER_RIM = QtGui.QColor(255, 255, 255, 22)

TEXT_PRIMARY = QtGui.QColor('#F2F2F7')
TEXT_HOVER = QtGui.QColor('#FFFFFF')
TEXT_SECONDARY = QtGui.QColor('#9A9AA2')
TEXT_SECONDARY_HOVER = QtGui.QColor('#D4D4DC')
TEXT_MUTED = QtGui.QColor('#6C6C74')
ACCENT_BLUE = QtGui.QColor('#3A82F7')

# Concentric Corner Radius: R_outer (11) = R_inner (6) + Padding (5)
R_OUTER = 11.0
PADDING = 5
R_INNER = 6.0

ROW_HEIGHT = 30
SEP_HEIGHT = 9
SHADOW_PAD = 24
TOP_ANIM_HEADROOM = 20  # Extra top space so translateY(-18px) never clips
ANIM_DURATION_SEC = 0.480  # 480ms Dropdown Inertia Unfurl


def _strip_mnemonic(text: str) -> str:
    """Convert Qt mnemonic labels like '&File' or 'Cu&t' & '&&' cleanly."""
    if not text:
        return ''
    placeholder = '\x00'
    s = text.replace('&&', placeholder).replace('&', '')
    return s.replace(placeholder, '&')


def _cubic_bezier_1d(p1: float, p2: float, t: float) -> float:
    u = 1.0 - t
    return 3.0 * u * u * t * p1 + 3.0 * u * t * t * p2 + t * t * t


def _cubic_bezier_deriv(p1: float, p2: float, t: float) -> float:
    u = 1.0 - t
    return 3.0 * u * u * p1 + 6.0 * u * t * (p2 - p1) + 3.0 * t * t * (1.0 - p2)


def eval_cubic_bezier(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """Exact solver for CSS cubic-bezier(x1, y1, x2, y2) at normalized time x."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    t = x
    for _ in range(6):
        dx = _cubic_bezier_1d(x1, x2, t) - x
        if abs(dx) < 1e-6:
            break
        d = _cubic_bezier_deriv(x1, x2, t)
        if abs(d) < 1e-6:
            break
        t = max(0.0, min(1.0, t - dx / d))
    return _cubic_bezier_1d(y1, y2, t)


def dropdown_unfurl_state(raw_t: float) -> tuple[float, float, float, float]:
    """Compute (opacity, translateY, scaleX, scaleY) for Penart 480ms unfurl.

    Matches playDropdownInertiaUnfurl() 3-keyframe spec with
    easing: cubic-bezier(0.16, 1, 0.3, 1).
    """
    u = eval_cubic_bezier(0.16, 1.0, 0.3, 1.0, max(0.0, min(1.0, raw_t)))
    if u <= 0.46:
        k = u / 0.46 if u > 0 else 0.0
        opacity = 0.0 + (0.92 - 0.0) * k
        ty = -18.0 + (-3.0 - (-18.0)) * k
        sy = 0.76 + (0.97 - 0.76) * k
        sx = 0.94 + (0.99 - 0.94) * k
    else:
        k = (u - 0.46) / 0.54
        opacity = 0.92 + (1.0 - 0.92) * k
        ty = -3.0 + (0.0 - (-3.0)) * k
        sy = 0.97 + (1.0 - 0.97) * k
        sx = 0.99 + (1.0 - 0.99) * k
    return opacity, ty, sx, sy


def _separable_box_blur_qimage(img: QtGui.QImage, radius: int, passes: int = 3) -> QtGui.QImage:
    """Fast true Gaussian-convergent blur via smooth multi-scale pyramid + 3x3 smoothing."""
    # Downscale smoothly, run fast 5-tap kernel on tiny buffer, upscale smoothly
    orig_w, orig_h = img.width(), img.height()
    dpr = img.devicePixelRatio()
    scale_div = max(2, radius // 3)
    sw = max(4, orig_w // scale_div)
    sh = max(4, orig_h // scale_div)

    cur = img.scaled(
        sw, sh,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QtGui.QImage.Format.Format_ARGB32)

    # 2 passes of separable [1, 2, 3, 2, 1]/9 box-tent kernel on the tiny image (~50x70 px -> <0.3ms!)
    for _ in range(passes):
        tmp = QtGui.QImage(sw, sh, QtGui.QImage.Format.Format_ARGB32)
        for y in range(sh):
            for x in range(sw):
                r_s = g_s = b_s = a_s = 0
                for dx, wt in ((-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1)):
                    xx = min(sw - 1, max(0, x + dx))
                    c = cur.pixelColor(xx, y)
                    r_s += c.red() * wt
                    g_s += c.green() * wt
                    b_s += c.blue() * wt
                    a_s += c.alpha() * wt
                tmp.setPixelColor(x, y, QtGui.QColor(r_s // 9, g_s // 9, b_s // 9, a_s // 9))

        for y in range(sh):
            for x in range(sw):
                r_s = g_s = b_s = a_s = 0
                for dy, wt in ((-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1)):
                    yy = min(sh - 1, max(0, y + dy))
                    c = tmp.pixelColor(x, yy)
                    r_s += c.red() * wt
                    g_s += c.green() * wt
                    b_s += c.blue() * wt
                    a_s += c.alpha() * wt
                cur.setPixelColor(x, y, QtGui.QColor(r_s // 9, g_s // 9, b_s // 9, a_s // 9))

    out = cur.scaled(
        orig_w, orig_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out.setDevicePixelRatio(dpr)
    return out


def _make_frosted_backdrop(
    global_rect: QtCore.QRect,
    parent_window: QtWidgets.QWidget | None = None,
) -> QtGui.QPixmap:
    """Capture exact canvas + artwork beneath menu, apply 20px blur + 150% saturation."""
    w, h = max(1, global_rect.width()), max(1, global_rect.height())
    dpr = 1.0
    app = QtWidgets.QApplication.instance()
    if app and app.primaryScreen():
        dpr = app.primaryScreen().devicePixelRatio()

    pw = max(1, round(w * dpr))
    ph = max(1, round(h * dpr))
    canvas_img = QtGui.QImage(pw, ph, QtGui.QImage.Format.Format_ARGB32)
    canvas_img.setDevicePixelRatio(dpr)
    canvas_img.fill(QtGui.QColor(28, 28, 34))

    view = getattr(parent_window, 'view', None) if parent_window is not None else None
    if view is not None:
        gp = QtGui.QPainter(canvas_img)
        # Fill base with active canvas color, then render live scene items directly!
        gp.fillRect(QtCore.QRectF(0, 0, w, h), view.backgroundBrush())
        local_tl = view.viewport().mapFromGlobal(global_rect.topLeft())
        vp_rect = QtCore.QRect(local_tl, QtCore.QSize(w, h))
        scene_poly = view.mapToScene(vp_rect)
        scene_rect = scene_poly.boundingRect()
        if not scene_rect.isEmpty():
            view.scene.render(
                gp,
                QtCore.QRectF(0, 0, w, h),
                scene_rect,
                Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        gp.end()

    # Boost saturation ~150% on small intermediate buffer before blur
    small_w = max(8, w // 4)
    small_h = max(8, h // 4)
    small = canvas_img.scaled(
        small_w, small_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QtGui.QImage.Format.Format_ARGB32)

    for yy in range(small_h):
        for xx in range(small_w):
            c = small.pixelColor(xx, yy)
            hue, sat, val, alpha = c.getHsv()
            if hue >= 0 and sat > 0:
                sat = min(255, int(sat * 1.50))
                c.setHsv(hue, sat, val, alpha)
                small.setPixelColor(xx, yy, c)

    up = small.scaled(
        pw, ph,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    up.setDevicePixelRatio(dpr)
    blurred = _separable_box_blur_qimage(up, radius=18, passes=2)
    return QtGui.QPixmap.fromImage(blurred)


def _bake_drop_shadow(card_w: int, card_h: int, pad: int, top_extra: int) -> QtGui.QPixmap:
    """True zero-banding Gaussian drop shadow (`0 12px 28px rgba(0,0,0,0.48)`)."""
    total_w = card_w + pad * 2
    total_h = card_h + pad * 2 + top_extra
    dpr = 1.0
    app = QtWidgets.QApplication.instance()
    if app and app.primaryScreen():
        dpr = app.primaryScreen().devicePixelRatio()

    pw = max(1, round(total_w * dpr))
    ph = max(1, round(total_h * dpr))
    raw = QtGui.QImage(pw, ph, QtGui.QImage.Format.Format_ARGB32)
    raw.setDevicePixelRatio(dpr)
    raw.fill(QtCore.Qt.GlobalColor.transparent)

    p = QtGui.QPainter(raw)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 125))
    sh_rect = QtCore.QRectF(
        float(pad) + 1.0,
        float(pad + top_extra) + 6.0,
        float(card_w) - 2.0,
        float(card_h) - 2.0,
    )
    p.drawRoundedRect(sh_rect, R_OUTER, R_OUTER)
    p.end()

    blurred = _separable_box_blur_qimage(raw, radius=15, passes=2)
    return QtGui.QPixmap.fromImage(blurred)


@dataclass
class _MenuEntry:
    kind: str  # 'action', 'submenu', 'separator'
    label: str = ''
    shortcut: str = ''
    enabled: bool = True
    checkable: bool = False
    checked: bool = False
    qaction: QtGui.QAction | None = None
    qmenu: QtWidgets.QMenu | None = None
    y_top: int = 0
    height: int = ROW_HEIGHT


class _PenartMenuPanel(QtWidgets.QWidget):
    """Single floating Penart frosted-glass dropdown panel."""

    def __init__(
        self,
        qmenu: QtWidgets.QMenu,
        controller: 'PenartMenuController',
        depth: int = 0,
    ):
        flags = (
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self.qmenu = qmenu
        self.controller = controller
        self.depth = depth
        self.hovered_index: int = -1
        self.active_submenu_index: int = -1
        self.origin_right: bool = False

        self.font_label = QtGui.QFont('Segoe UI', 10)
        self.font_label.setWeight(QtGui.QFont.Weight.Normal)
        self.font_shortcut = QtGui.QFont('Segoe UI', 9)

        self.entries: list[_MenuEntry] = self._extract_entries(qmenu)
        self.has_any_checkable = any(e.checkable for e in self.entries)
        self.card_w, self.card_h = self._measure_card()

        self.win_w = self.card_w + SHADOW_PAD * 2
        self.win_h = self.card_h + SHADOW_PAD * 2 + TOP_ANIM_HEADROOM
        self.card_rect = QtCore.QRectF(
            SHADOW_PAD,
            SHADOW_PAD + TOP_ANIM_HEADROOM,
            self.card_w,
            self.card_h,
        )

        self.setFixedSize(self.win_w, self.win_h)
        self._shadow_pm: QtGui.QPixmap | None = None
        self._frosted_pm: QtGui.QPixmap | None = None

        self._anim_start = 0.0
        self._anim_raw_t = 0.0
        self._anim_timer = QtCore.QTimer(self)
        self._anim_timer.setInterval(8)  # ~120 FPS
        self._anim_timer.timeout.connect(self._on_anim_tick)

    def _extract_entries(self, qmenu: QtWidgets.QMenu) -> list[_MenuEntry]:
        raw: list[_MenuEntry] = []
        for act in qmenu.actions():
            if not act.isVisible():
                continue
            if act.isSeparator():
                # Collapse leading or consecutive separators
                if not raw or raw[-1].kind == 'separator':
                    continue
                raw.append(_MenuEntry(kind='separator', height=SEP_HEIGHT))
                continue

            sub = act.menu()
            if sub is not None:
                has_items = any(
                    not a.isSeparator() and a.isVisible() for a in sub.actions()
                )
                raw.append(_MenuEntry(
                    kind='submenu',
                    label=_strip_mnemonic(sub.title() or act.text()),
                    enabled=act.isEnabled() and has_items,
                    qaction=act,
                    qmenu=sub,
                    height=ROW_HEIGHT,
                ))
            else:
                sc = act.shortcut().toString(
                    QtGui.QKeySequence.SequenceFormat.NativeText)
                raw.append(_MenuEntry(
                    kind='action',
                    label=_strip_mnemonic(act.text()),
                    shortcut=sc,
                    enabled=act.isEnabled(),
                    checkable=act.isCheckable(),
                    checked=act.isChecked(),
                    qaction=act,
                    height=ROW_HEIGHT,
                ))

        while raw and raw[-1].kind == 'separator':
            raw.pop()

        if not raw:
            raw.append(_MenuEntry(
                kind='action',
                label='Empty',
                enabled=False,
                height=ROW_HEIGHT,
            ))

        y = PADDING
        for e in raw:
            e.y_top = y
            y += e.height
        return raw

    def _measure_card(self) -> tuple[int, int]:
        fm_lbl = QtGui.QFontMetrics(self.font_label)
        fm_sc = QtGui.QFontMetrics(self.font_shortcut)

        check_gutter = 22 if self.has_any_checkable else 6
        max_row_w = 156

        for e in self.entries:
            if e.kind == 'separator':
                continue
            lbl_w = fm_lbl.horizontalAdvance(e.label)
            right_w = 0
            if e.kind == 'submenu':
                right_w = 24
            elif e.shortcut:
                right_w = fm_sc.horizontalAdvance(e.shortcut) + 24
            row_w = PADDING * 2 + check_gutter + lbl_w + right_w + 14
            if row_w > max_row_w:
                max_row_w = row_w

        total_h = PADDING * 2 + sum(e.height for e in self.entries)
        return max_row_w, total_h

    def popup_at(
        self,
        global_anchor: QtCore.QPoint,
        parent_window: QtWidgets.QWidget | None = None,
        prefer_right_of_rect: QtCore.QRect | None = None,
    ):
        screen = QtGui.QGuiApplication.screenAt(global_anchor)
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1920, 1080)

        if prefer_right_of_rect is not None:
            # Submenu placement beside parent row
            cand_x = prefer_right_of_rect.right() + 4
            if cand_x + self.card_w > avail.right() - 6:
                cand_x = prefer_right_of_rect.left() - self.card_w - 4
                self.origin_right = True
            else:
                self.origin_right = False
            cand_y = prefer_right_of_rect.top() - PADDING
        else:
            cand_x = global_anchor.x()
            if cand_x + self.card_w > avail.right() - 6:
                cand_x = max(avail.left() + 6, global_anchor.x() - self.card_w)
                self.origin_right = True
            else:
                self.origin_right = False
            cand_y = global_anchor.y()

        cand_y = max(avail.top() + 6, min(cand_y, avail.bottom() - self.card_h - 6))
        cand_x = max(avail.left() + 6, min(cand_x, avail.right() - self.card_w - 6))

        target_global_card = QtCore.QRect(cand_x, cand_y, self.card_w, self.card_h)
        self._frosted_pm = _make_frosted_backdrop(target_global_card, parent_window)
        self._shadow_pm = _bake_drop_shadow(
            self.card_w, self.card_h, SHADOW_PAD, TOP_ANIM_HEADROOM)

        win_x = cand_x - SHADOW_PAD
        win_y = cand_y - SHADOW_PAD - TOP_ANIM_HEADROOM
        self.move(win_x, win_y)

        self._anim_start = time.perf_counter()
        self._anim_raw_t = 0.0
        self.show()
        self.raise_()
        self._anim_timer.start()

    def _on_anim_tick(self):
        elapsed = time.perf_counter() - self._anim_start
        if elapsed >= ANIM_DURATION_SEC:
            self._anim_raw_t = 1.0
            self._anim_timer.stop()
        else:
            self._anim_raw_t = elapsed / ANIM_DURATION_SEC
        self.update()

    def global_card_rect(self) -> QtCore.QRect:
        tl = self.mapToGlobal(QtCore.QPoint(
            int(self.card_rect.left()), int(self.card_rect.top())))
        return QtCore.QRect(tl.x(), tl.y(), self.card_w, self.card_h)

    def global_row_rect(self, index: int) -> QtCore.QRect:
        e = self.entries[index]
        tl = self.mapToGlobal(QtCore.QPoint(
            int(self.card_rect.left()),
            int(self.card_rect.top()) + e.y_top,
        ))
        return QtCore.QRect(tl.x(), tl.y(), self.card_w, e.height)

    def entry_index_at_global(self, gpos: QtCore.QPoint) -> int:
        local = self.mapFromGlobal(gpos)
        if not self.card_rect.contains(QtCore.QPointF(local)):
            return -1
        rel_y = local.y() - int(self.card_rect.top())
        for idx, e in enumerate(self.entries):
            if e.y_top <= rel_y < e.y_top + e.height:
                return idx if e.kind != 'separator' else -1
        return -1

    def set_hovered_index(self, idx: int):
        if idx != self.hovered_index:
            self.hovered_index = idx
            self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        opacity, ty, sx, sy = dropdown_unfurl_state(self._anim_raw_t)
        if opacity <= 0.002:
            painter.end()
            return

        pivot_x = (
            self.card_rect.right() if self.origin_right else self.card_rect.left()
        )
        pivot_y = self.card_rect.top()

        painter.setOpacity(opacity)
        painter.translate(pivot_x, pivot_y + ty)
        painter.scale(sx, sy)
        painter.translate(-pivot_x, -pivot_y)

        # 1. Soft Elevation Drop Shadow
        if self._shadow_pm is not None:
            painter.drawPixmap(0, 0, self._shadow_pm)

        # 2. Rounded Card Clip Path (R_outer = 11px)
        card_path = QtGui.QPainterPath()
        card_path.addRoundedRect(self.card_rect, R_OUTER, R_OUTER)

        painter.save()
        painter.setClipPath(card_path)

        # Frosted Backdrop Blur + Dark Matte Glass Tint
        if self._frosted_pm is not None:
            painter.drawPixmap(
                int(self.card_rect.left()),
                int(self.card_rect.top()),
                self._frosted_pm,
            )
        painter.fillRect(self.card_rect, BG_GLASS_TINT)

        # Top 1px Specular Inner Highlight
        top_hl_pen = QtGui.QPen(RIM_TOP_INSET, 1.0)
        painter.setPen(top_hl_pen)
        painter.drawLine(
            QtCore.QPointF(self.card_rect.left() + R_OUTER * 0.6, self.card_rect.top() + 1.0),
            QtCore.QPointF(self.card_rect.right() - R_OUTER * 0.6, self.card_rect.top() + 1.0),
        )

        # 3. Entries (Concentric inner pill R_inner = 6px with 5px padding)
        check_gutter = 22 if self.has_any_checkable else 6
        cx = self.card_rect.left()
        cy = self.card_rect.top()

        for idx, e in enumerate(self.entries):
            if e.kind == 'separator':
                sep_y = cy + e.y_top + e.height * 0.5
                painter.setPen(QtGui.QPen(RIM_SEPARATOR, 1.0))
                painter.drawLine(
                    QtCore.QPointF(cx + PADDING + 6, sep_y),
                    QtCore.QPointF(cx + self.card_w - PADDING - 6, sep_y),
                )
                continue

            row_rect = QtCore.QRectF(
                cx + PADDING,
                cy + e.y_top,
                self.card_w - PADDING * 2,
                e.height,
            )
            is_hi = (
                e.enabled
                and (idx == self.hovered_index or idx == self.active_submenu_index)
            )

            if is_hi:
                pill_path = QtGui.QPainterPath()
                pill_path.addRoundedRect(row_rect, R_INNER, R_INNER)
                painter.fillPath(pill_path, HOVER_BG)
                painter.setPen(QtGui.QPen(HOVER_RIM, 1.0))
                painter.drawPath(pill_path)

            # Checkmark badge for checkable actions
            if e.checkable and e.checked:
                badge_sz = 15.0
                bx = row_rect.left() + 6.0
                by = row_rect.center().y() - badge_sz * 0.5
                badge_rect = QtCore.QRectF(bx, by, badge_sz, badge_sz)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ACCENT_BLUE if e.enabled else TEXT_MUTED)
                painter.drawRoundedRect(badge_rect, 4.2, 4.2)

                # Crisp vector tick
                ck_pen = QtGui.QPen(QtGui.QColor('#FFFFFF'), 1.7)
                ck_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                ck_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(ck_pen)
                p1 = QtCore.QPointF(bx + 3.6, by + 7.8)
                p2 = QtCore.QPointF(bx + 6.4, by + 10.6)
                p3 = QtCore.QPointF(bx + 11.5, by + 4.6)
                painter.drawLine(p1, p2)
                painter.drawLine(p2, p3)
                painter.setBrush(Qt.BrushStyle.NoBrush)

            # Primary Label
            painter.setFont(self.font_label)
            if not e.enabled:
                painter.setPen(TEXT_MUTED)
            elif is_hi:
                painter.setPen(TEXT_HOVER)
            else:
                painter.setPen(TEXT_PRIMARY)

            text_rect = QtCore.QRectF(
                row_rect.left() + check_gutter + 4,
                row_rect.top(),
                row_rect.width() - check_gutter - 12,
                row_rect.height(),
            )
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                e.label,
            )

            # Right-side Shortcut or Submenu Chevron '›'
            if e.kind == 'submenu':
                chev_color = (
                    TEXT_MUTED if not e.enabled
                    else (TEXT_SECONDARY_HOVER if is_hi else TEXT_SECONDARY)
                )
                chev_pen = QtGui.QPen(chev_color, 1.5)
                chev_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                chev_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(chev_pen)
                rx = row_rect.right() - 11.0
                ry = row_rect.center().y()
                painter.drawLine(
                    QtCore.QPointF(rx - 3.5, ry - 4.0),
                    QtCore.QPointF(rx + 0.5, ry),
                )
                painter.drawLine(
                    QtCore.QPointF(rx + 0.5, ry),
                    QtCore.QPointF(rx - 3.5, ry + 4.0),
                )
            elif e.shortcut:
                painter.setFont(self.font_shortcut)
                painter.setPen(
                    TEXT_MUTED if not e.enabled
                    else (TEXT_SECONDARY_HOVER if is_hi else TEXT_SECONDARY)
                )
                sc_rect = QtCore.QRectF(
                    row_rect.left() + check_gutter,
                    row_rect.top(),
                    row_rect.width() - check_gutter - 9,
                    row_rect.height(),
                )
                painter.drawText(
                    sc_rect,
                    int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                    e.shortcut,
                )

        painter.restore()

        # 4. Outer 1px Specular Hairline Rim
        rim_rect = self.card_rect.adjusted(0.5, 0.5, -0.5, -0.5)
        rim_path = QtGui.QPainterPath()
        rim_path.addRoundedRect(rim_rect, R_OUTER - 0.5, R_OUTER - 0.5)
        painter.setPen(QtGui.QPen(RIM_OUTER, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(rim_path)

        painter.end()


class PenartMenuController(QtCore.QObject):
    """Coordinates root + nested Penart dropdown panels seamlessly."""

    _active_instance: 'PenartMenuController | None' = None

    def __init__(self, parent_widget: QtWidgets.QWidget):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self.panels: list[_PenartMenuPanel] = []
        self._submenu_timer = QtCore.QTimer(self)
        self._submenu_timer.setSingleShot(True)
        self._submenu_timer.setInterval(90)
        self._submenu_timer.timeout.connect(self._open_pending_submenu)
        self._pending_submenu: tuple[int, int] | None = None

    @classmethod
    def popup(cls, qmenu: QtWidgets.QMenu, global_pos: QtCore.QPoint, parent_widget: QtWidgets.QWidget):
        if cls._active_instance is not None:
            cls._active_instance.close_all()

        ctrl = cls(parent_widget)
        cls._active_instance = ctrl
        ctrl._open_root(qmenu, global_pos)

    def _open_root(self, qmenu: QtWidgets.QMenu, global_pos: QtCore.QPoint):
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        root = _PenartMenuPanel(qmenu, self, depth=0)
        self.panels.append(root)
        main_win = self.parent_widget.window()
        root.popup_at(global_pos, parent_window=main_win)

    def close_all(self):
        self._submenu_timer.stop()
        self._pending_submenu = None
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

        for panel in reversed(self.panels):
            panel.hide()
            panel.deleteLater()
        self.panels.clear()

        if PenartMenuController._active_instance is self:
            PenartMenuController._active_instance = None

    def _close_deeper_than(self, depth: int):
        while len(self.panels) > depth + 1:
            child = self.panels.pop()
            child.hide()
            child.deleteLater()
        if depth < len(self.panels):
            self.panels[depth].active_submenu_index = -1
            self.panels[depth].update()

    def _schedule_submenu(self, depth: int, entry_idx: int):
        self._pending_submenu = (depth, entry_idx)
        self._submenu_timer.start()

    def _open_pending_submenu(self):
        if self._pending_submenu is None:
            return
        depth, entry_idx = self._pending_submenu
        self._pending_submenu = None

        if depth >= len(self.panels):
            return
        parent_panel = self.panels[depth]
        if entry_idx < 0 or entry_idx >= len(parent_panel.entries):
            self._close_deeper_than(depth)
            return

        entry = parent_panel.entries[entry_idx]
        if entry.kind != 'submenu' or not entry.enabled or entry.qmenu is None:
            self._close_deeper_than(depth)
            return

        if parent_panel.active_submenu_index == entry_idx and len(self.panels) > depth + 1:
            return

        self._close_deeper_than(depth)
        parent_panel.active_submenu_index = entry_idx
        parent_panel.update()

        row_rect = parent_panel.global_row_rect(entry_idx)
        sub_panel = _PenartMenuPanel(entry.qmenu, self, depth=depth + 1)
        self.panels.append(sub_panel)
        sub_panel.popup_at(
            row_rect.topRight(),
            parent_window=self.parent_widget.window(),
            prefer_right_of_rect=row_rect,
        )

    def _trigger_entry(self, panel: _PenartMenuPanel, idx: int):
        if idx < 0 or idx >= len(panel.entries):
            return
        entry = panel.entries[idx]
        if not entry.enabled:
            return
        if entry.kind == 'submenu':
            self._pending_submenu = (panel.depth, idx)
            self._open_pending_submenu()
            return
        if entry.kind == 'action' and entry.qaction is not None:
            act = entry.qaction
            self.close_all()
            # Trigger on next event loop tick so modal dialogs open cleanly
            QtCore.QTimer.singleShot(0, act.trigger)

    def _panel_at_global(self, gpos: QtCore.QPoint) -> _PenartMenuPanel | None:
        # Check from deepest child submenu down to root
        for panel in reversed(self.panels):
            if panel.global_card_rect().contains(gpos):
                return panel
        return None

    def eventFilter(self, obj, event):
        etype = event.type()

        if etype == QtCore.QEvent.Type.MouseMove:
            gpos = event.globalPosition().toPoint()
            panel = self._panel_at_global(gpos)
            if panel is not None:
                # Clear hover on deeper panels if cursor moved back to parent
                for p in self.panels:
                    if p is not panel and p.hovered_index != -1:
                        p.set_hovered_index(-1)
                idx = panel.entry_index_at_global(gpos)
                if idx != panel.hovered_index:
                    panel.set_hovered_index(idx)
                    self._schedule_submenu(panel.depth, idx)
            else:
                for p in self.panels:
                    p.set_hovered_index(-1)
            return False

        if etype in (
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QEvent.Type.MouseButtonDblClick,
        ):
            gpos = event.globalPosition().toPoint()
            panel = self._panel_at_global(gpos)
            if panel is None:
                self.close_all()
                # Consume right-click outside if user wants to dismiss, or
                # if right-click inside view, let view open new menu at new pos!
                if event.button() == Qt.MouseButton.RightButton:
                    return False
                return True

            idx = panel.entry_index_at_global(gpos)
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                self._trigger_entry(panel, idx)
            return True

        if etype == QtCore.QEvent.Type.MouseButtonRelease:
            gpos = event.globalPosition().toPoint()
            if self._panel_at_global(gpos) is not None:
                return True
            return False

        if etype == QtCore.QEvent.Type.Wheel:
            self.close_all()
            return False

        if etype == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close_all()
                return True
            if self.panels:
                top = self.panels[-1]
                enabled_indices = [
                    i for i, e in enumerate(top.entries)
                    if e.kind != 'separator' and e.enabled
                ]
                if key == Qt.Key.Key_Down and enabled_indices:
                    cur = top.hovered_index
                    nxt = enabled_indices[0]
                    for i in enabled_indices:
                        if i > cur:
                            nxt = i
                            break
                    top.set_hovered_index(nxt)
                    return True
                if key == Qt.Key.Key_Up and enabled_indices:
                    cur = top.hovered_index
                    prv = enabled_indices[-1]
                    for i in reversed(enabled_indices):
                        if i < cur:
                            prv = i
                            break
                    top.set_hovered_index(prv)
                    return True
                if key == Qt.Key.Key_Right and top.hovered_index >= 0:
                    e = top.entries[top.hovered_index]
                    if e.kind == 'submenu' and e.enabled:
                        self._pending_submenu = (top.depth, top.hovered_index)
                        self._open_pending_submenu()
                        if len(self.panels) > top.depth + 1:
                            child = self.panels[-1]
                            for idx, ce in enumerate(child.entries):
                                if ce.kind != 'separator' and ce.enabled:
                                    child.set_hovered_index(idx)
                                    break
                        return True
                if key == Qt.Key.Key_Left and len(self.panels) > 1:
                    self._close_deeper_than(len(self.panels) - 2)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and top.hovered_index >= 0:
                    self._trigger_entry(top, top.hovered_index)
                    return True

        if etype == QtCore.QEvent.Type.ApplicationDeactivate:
            self.close_all()
            return False

        return super().eventFilter(obj, event)
