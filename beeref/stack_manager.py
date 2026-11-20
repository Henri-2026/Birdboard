# This file is part of Birdboard (GPL-3.0-or-later).

"""Stack Group Manager: Collapsed Physical Pile, Spread Grid, Canvas Wash,
Cover Priority Ordering, and Live Pull-Out Reflow at 120 FPS.
"""

import math
import random
import time
import uuid

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
import rpack

from beeref import constants
from beeref.assets import BeeAssets
from beeref.deskboard_motion import (
    SPRING_PLACE,
    SPRING_POP,
    collapse_flight_factor,
    cubic_bezier,
    spread_flight_factor,
)


MAX_VISIBLE_UNDERLAYS = 12


def _compute_collage_offsets(
    stack_id: str,
    total_count: int,
    underlay_count: int,
) -> list[tuple[float, float, float, float]]:
    """Generate deterministic Deskboard-style seeded collage offsets with subtle rotation.

    Cover card always sits at (0, 0) offset and 0 deg rotation so the stack's
    canonical center is 100% locked to `cover.center_scene_coords`.
    Underlay cards fan out around Cover with seeded (dx, dy) offsets and gentle
    micro-rotation (±1.0° .. ±3.0°) like Deskboard (Hình 4).
    Returns:
        underlay_specs: list of (dx_ratio, dy_ratio, area_scale_factor, tilt_deg)
    """
    if underlay_count <= 0:
        return []

    rng = random.Random(f'birdboard-collage-v3-{stack_id}')

    near_sectors = [
        (-0.15, -0.11),
        ( 0.14, -0.10),
        (-0.18,  0.03),
        (-0.02, -0.19),
        ( 0.16,  0.04),
        (-0.12, -0.21),
    ]
    deep_sectors = [
        ( 0.11, -0.22),
        (-0.21, -0.05),
        ( 0.03, -0.26),
        ( 0.19, -0.06),
        (-0.09, -0.30),
        ( 0.09, -0.31),
    ]
    rng.shuffle(near_sectors)
    rng.shuffle(deep_sectors)
    sectors = near_sectors + deep_sectors

    depth_boost = (
        min(1.32, 1.0 + 0.09 * math.log2(max(1.0, total_count / 5.0)))
        if total_count >= 6 else 0.88
    )

    specs: list[tuple[float, float, float, float]] = []
    for k in range(underlay_count):
        bx, by = sectors[k % len(sectors)]
        jx = rng.uniform(-0.038, 0.038)
        jy = rng.uniform(-0.032, 0.032)
        dx = (bx + jx) * min(1.12, depth_boost)
        dy = (by + jy) * depth_boost
        area_mult = rng.uniform(0.87, 0.96)
        # Alternating gentle micro-rotation (±1.0° .. ±2.8°) for clear back-card separation
        sign = 1.0 if (k % 2 == 0) else -1.0
        if rng.random() < 0.25:
            sign = -sign
        tilt_deg = sign * rng.uniform(1.0, 2.8)
        specs.append((dx, dy, area_mult, tilt_deg))

    return specs


def sort_stack_members(items: list) -> list:
    """Order Stack members with Cover Image (`is_stack_cover=True`) ALWAYS #0.

    Never sorts by filename so user-chosen Group Cover stays on top!
    """
    covers = [it for it in items if getattr(it, 'is_stack_cover', False)]
    others = [it for it in items if not getattr(it, 'is_stack_cover', False)]
    others.sort(key=lambda it: (
        getattr(it, 'stack_order', 0),
        getattr(it, 'save_id', 0) or 0,
    ))
    return covers + others


class CanvasWashItem(QtWidgets.QGraphicsRectItem):
    """Translucent canvas-colored scrim (`alpha = 0.80`) behind a Spread Stack."""

    def __init__(self):
        super().__init__()
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setPen(QtGui.QPen(Qt.PenStyle.NoPen))
        self.refresh_color()
        self.setOpacity(0.0)

    def refresh_color(self):
        col = QtGui.QColor(*constants.COLORS['Scene:Canvas'])
        self.setBrush(QtGui.QBrush(col))


class StackOverlayLabelItem(QtWidgets.QGraphicsItem):
    """Non-interactive scene-space overlay for Collapsed Stack `[N]` and Group Name.

    Kept separate from `BeePixmapItem` so collapsed group labels never inflate
    card `boundingRect()` inside Qt's C++ `BspTreeIndex`.
    """

    def __init__(self, stack_id: str):
        super().__init__()
        self.stack_id = stack_id
        self._pile_rect = QtCore.QRectF(0.0, 0.0, 1.0, 1.0)
        self._bound_rect = QtCore.QRectF(0.0, 0.0, 1.0, 1.0)
        self._count = 0
        self._stack_name = ''
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
            False,
        )

    def boundingRect(self) -> QtCore.QRectF:
        return self._bound_rect

    def shape(self) -> QtGui.QPainterPath:
        return QtGui.QPainterPath()

    def contains(self, point: QtCore.QPointF) -> bool:
        return False

    def sync_geometry(
        self,
        scene_pile_rect: QtCore.QRectF,
        px_to_scene: float,
        count: int,
        stack_name: str,
        z_val: float,
    ):
        local_pile = QtCore.QRectF(
            0.0,
            0.0,
            max(1.0, scene_pile_rect.width()),
            max(1.0, scene_pile_rect.height()),
        )
        pad_x = max(90.0 * px_to_scene, local_pile.width() * 0.30)
        pad_top = 30.0 * px_to_scene
        pad_bot = 36.0 * px_to_scene
        new_bound = local_pile.adjusted(-pad_x, -pad_top, pad_x, pad_bot)

        self.prepareGeometryChange()
        self._pile_rect = local_pile
        self._bound_rect = new_bound
        self._count = count
        self._stack_name = stack_name
        self.setPos(scene_pile_rect.topLeft())
        self.setZValue(z_val)
        self.update()

    def paint(self, painter: QtGui.QPainter, option, widget=None):
        if self._count < 2:
            return
        ct = painter.combinedTransform()
        item_to_device = math.hypot(ct.m11(), ct.m12())
        dev = painter.device()
        dpr = max(1.0, float(dev.devicePixelRatioF())) if dev is not None else 1.0
        item_to_logical = item_to_device / dpr
        if item_to_logical <= 1e-5:
            return
        pile_r = self._pile_rect
        if (pile_r.width() * item_to_logical) < 24.0:
            return

        px_unit = 1.0 / item_to_logical
        is_dark = (constants.ACTIVE_THEME == 'dark')
        assets = BeeAssets()

        # 1. [N] count right-aligned 6.0 * px_unit above top-right corner of scene_pile_rect
        painter.save()
        cnt_txt = f'[{self._count}]'
        f_cnt = assets.font(11, 300)
        painter.setFont(f_cnt)
        fm_c = QtGui.QFontMetrics(f_cnt)
        cw = fm_c.horizontalAdvance(cnt_txt) + 6
        ch = fm_c.height() + 2

        anchor_x = pile_r.right() - 2.0 * px_unit
        anchor_y = pile_r.top() - 6.0 * px_unit
        painter.translate(anchor_x, anchor_y)
        painter.scale(px_unit, px_unit)
        c_rect = QtCore.QRectF(-float(cw), -float(ch), float(cw), float(ch))
        c_align = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        cnt_col = QtGui.QColor('#A0A2AA') if is_dark else QtGui.QColor('#52545B')
        painter.setPen(cnt_col)
        painter.drawText(c_rect, c_align, cnt_txt)
        painter.restore()

        # 2. Group Name horizontally centered 8.0 * px_unit below scene_pile_rect.bottom()
        name_clean = self._stack_name.strip()
        if name_clean:
            painter.save()
            cx = pile_r.center().x()
            top_y = pile_r.bottom() + 8.0 * px_unit
            painter.translate(cx, top_y)
            painter.scale(px_unit, px_unit)

            f_name = assets.font(13, 300)
            painter.setFont(f_name)
            fm = QtGui.QFontMetrics(f_name)
            max_px_w = max(130, round((pile_r.width() / px_unit) + 90))
            elided = fm.elidedText(
                name_clean,
                Qt.TextElideMode.ElideRight,
                max_px_w,
            )
            tw = fm.horizontalAdvance(elided) + 12
            th = fm.height() + 4
            txt_rect = QtCore.QRectF(-tw * 0.5, 0.0, float(tw), float(th))

            fg = QtGui.QColor('#EAEAF0') if is_dark else QtGui.QColor('#1A1A1C')
            painter.setPen(fg)
            painter.drawText(
                txt_rect,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                elided,
            )
            painter.restore()


class StackManager(QtCore.QObject):
    """Manages all Stack Groups, animations, Spread sessions, and Pull-Out."""

    def __init__(self, scene):
        super().__init__(scene)
        self.scene = scene
        self.active_spread_stack_id: str | None = None
        self.spread_center = QtCore.QPointF(0.0, 0.0)
        self._has_spread_center = False
        self._spread_opened_t0 = 0.0
        self.spread_grid_rect = QtCore.QRectF()
        self.keep_zone = QtCore.QRectF()
        self._stack_centers: dict[str, QtCore.QPointF] = {}
        self._stack_counts: dict[str, int] = {}
        self._stack_vis_members: dict[str, list] = {}
        self._caches_dirty = True
        self._dirty_sids: set[str] = set()
        self._label_items: dict[str, StackOverlayLabelItem] = {}

        self.wash_item = CanvasWashItem()
        self._wash_from = 0.0
        self._wash_to = 0.0
        self._wash_t0 = 0.0
        self._wash_dur = 0.30
        self._wash_hide_on_done = False

        # Active item flight animations: item -> dict
        self._flights: dict[object, dict] = {}
        self._pop_targets: list[tuple[object, float]] = []
        self._pop_t0 = -1.0

        # Live Pull-Out state during Spread drag
        self._dragging_item = None
        self._pulled_out_preview = False
        self._drag_slot_targets: dict[object, QtCore.QPointF] = {}

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(8)  # 120 FPS
        self._timer.timeout.connect(self._on_tick)

    def clear(self):
        self._timer.stop()
        self._flights.clear()
        self._pop_targets.clear()
        self._pop_t0 = -1.0
        for lbl in list(self._label_items.values()):
            if lbl.scene() is self.scene:
                self.scene.removeItem(lbl)
        self._label_items.clear()
        self._stack_centers.clear()
        self._stack_counts.clear()
        self._stack_vis_members.clear()
        self._caches_dirty = True
        self._dirty_sids.clear()
        self.active_spread_stack_id = None
        self.spread_center = QtCore.QPointF(0.0, 0.0)
        self._has_spread_center = False
        self._spread_opened_t0 = 0.0
        self.spread_grid_rect = QtCore.QRectF()
        self.keep_zone = QtCore.QRectF()
        self._dragging_item = None
        self._pulled_out_preview = False
        self._drag_slot_targets.clear()
        if self.wash_item.scene() is self.scene:
            self.scene.removeItem(self.wash_item)
        self.wash_item = CanvasWashItem()

    def can_dismiss_spread_by_wash(self) -> bool:
        return (time.perf_counter() - self._spread_opened_t0) >= 0.28

    def cancel_flights_for(self, items):
        """Cancel any active flight or spring-pop animation for `items`."""
        item_set = set(items)
        if not item_set:
            return
        for it in item_set:
            self._flights.pop(it, None)
        if self._pop_targets:
            remaining_pops = []
            for pop_item, base_sc in self._pop_targets:
                if pop_item in item_set:
                    if pop_item.scene() is not None:
                        c = pop_item.center_scene_coords
                        tpos = self._pos_for_center_and_transform(
                            pop_item, c, base_sc, pop_item.rotation())
                        QtWidgets.QGraphicsItem.setScale(pop_item, base_sc)
                        pop_item.setPos(tpos)
                else:
                    remaining_pops.append((pop_item, base_sc))
            self._pop_targets = remaining_pops
            if not self._pop_targets:
                self._pop_t0 = -1.0
        if not self._flights and not self._pop_targets and not self.wash_item.scene():
            self._timer.stop()

    def _remove_label_item(self, stack_id: str):
        lbl = self._label_items.pop(stack_id, None)
        if lbl is not None and lbl.scene() is self.scene:
            self.scene.removeItem(lbl)

    def _ensure_caches(self):
        """Keep stack count & visible-member caches warm in O(1) when clean, O(N) once when dirty."""
        if self._caches_dirty:
            grouped: dict[str, list] = {}
            for it in self.scene.items():
                sid = getattr(it, 'stack_id', None)
                if sid and hasattr(it, 'save_id'):
                    grouped.setdefault(sid, []).append(it)
            self._stack_counts.clear()
            self._stack_vis_members.clear()
            for sid, raw in grouped.items():
                ordered = sort_stack_members(raw)
                self._stack_counts[sid] = len(ordered)
                self._stack_vis_members[sid] = [m for m in ordered if m.isVisible()]
            self._dirty_sids.clear()
            self._caches_dirty = False
        elif self._dirty_sids:
            for sid in list(self._dirty_sids):
                ordered = self.members_of(sid)
                if ordered:
                    self._stack_counts[sid] = len(ordered)
                    self._stack_vis_members[sid] = [m for m in ordered if m.isVisible()]
                else:
                    self._stack_counts.pop(sid, None)
                    self._stack_vis_members.pop(sid, None)
            self._dirty_sids.clear()

    def sync_stack_label(self, stack_id: str):
        """Synchronize the `StackOverlayLabelItem` for `stack_id`."""
        if not stack_id:
            return
        if self.active_spread_stack_id == stack_id:
            self._remove_label_item(stack_id)
            return

        cnt = self.stack_count_fast(stack_id)
        if cnt < 2:
            self._stack_counts.pop(stack_id, None)
            self._stack_vis_members.pop(stack_id, None)
            self._dirty_sids.discard(stack_id)
            self._remove_label_item(stack_id)
            return

        vis_members = self.visible_pile_members_fast(stack_id)
        if not vis_members:
            members = self.members_of(stack_id)
            cnt = len(members)
            if cnt < 2:
                self._stack_counts.pop(stack_id, None)
                self._stack_vis_members.pop(stack_id, None)
                self._dirty_sids.discard(stack_id)
                self._remove_label_item(stack_id)
                return
            self._stack_counts[stack_id] = cnt
            vis_members = [m for m in members if m.isVisible()]
            self._stack_vis_members[stack_id] = vis_members
            self._dirty_sids.discard(stack_id)
            if not vis_members:
                self._remove_label_item(stack_id)
                return

        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')
        for m in vis_members:
            r = m.sceneTransform().mapRect(m.bounding_rect_unselected())
            if r.left() < min_x:
                min_x = r.left()
            if r.top() < min_y:
                min_y = r.top()
            if r.right() > max_x:
                max_x = r.right()
            if r.bottom() > max_y:
                max_y = r.bottom()

        scene_pile_rect = QtCore.QRectF(
            QtCore.QPointF(min_x, min_y),
            QtCore.QPointF(max_x, max_y),
        )

        views = self.scene.views()
        raw_scale = (
            float(views[0].get_scale())
            if (views and hasattr(views[0], 'get_scale'))
            else 1.0
        )
        view_scale = max(0.02, raw_scale)
        lod_cap_px = max(1.0, scene_pile_rect.width()) / 20.0
        px_to_scene = min(
            1.0 / max(0.002, raw_scale),
            max(1.0 / view_scale, lod_cap_px),
        )

        cover = vis_members[0]
        z_val = cover.zValue() + self.scene.Z_STEP * 0.5
        stack_name = getattr(cover, 'stack_name', '')
        if not stack_name:
            for m in vis_members:
                nm = getattr(m, 'stack_name', '')
                if nm:
                    stack_name = nm
                    break

        lbl = self._label_items.get(stack_id)
        if lbl is None:
            lbl = StackOverlayLabelItem(stack_id)
            self._label_items[stack_id] = lbl

        lbl.sync_geometry(scene_pile_rect, px_to_scene, cnt, stack_name, z_val)
        if lbl.scene() is not self.scene:
            self.scene.addItem(lbl)

    def sync_selected_stack_labels(self):
        """Sync labels for `stack_id`s present in `self.scene.selectedItems(user_only=True)`."""
        sids = {
            it.stack_id for it in self.scene.selectedItems(user_only=True)
            if getattr(it, 'stack_id', None)
        }
        for sid in sids:
            self.sync_stack_label(sid)

    def sync_all_stack_labels(self):
        """Fast O(G) sync of all collapsed stack overlay labels."""
        self._ensure_caches()
        for stale_sid in list(self._label_items.keys()):
            if stale_sid not in self._stack_counts:
                self._remove_label_item(stale_sid)
        for sid in list(self._stack_counts.keys()):
            self.sync_stack_label(sid)

    def stack_count_fast(self, stack_id: str | None) -> int:
        if not stack_id:
            return 0
        cnt = self._stack_counts.get(stack_id)
        if cnt is None:
            members = self.members_of(stack_id)
            cnt = len(members)
            if cnt > 0:
                self._stack_counts[stack_id] = cnt
                self._stack_vis_members[stack_id] = [m for m in members if m.isVisible()]
            self._dirty_sids.discard(stack_id)
        return cnt

    def visible_pile_members_fast(self, stack_id: str | None) -> list:
        if not stack_id:
            return []
        vis = self._stack_vis_members.get(stack_id)
        if vis is not None:
            return [m for m in vis if m.scene() is self.scene and m.isVisible()]
        members = self.members_of(stack_id)
        vis_m = [m for m in members if m.isVisible()]
        if members:
            self._stack_counts[stack_id] = len(members)
            self._stack_vis_members[stack_id] = vis_m
        self._dirty_sids.discard(stack_id)
        return vis_m

    def invalidate_stack_cache(self, stack_id: str | None = None):
        if stack_id is None:
            self._stack_counts.clear()
            self._stack_vis_members.clear()
            self._dirty_sids.clear()
            self._caches_dirty = True
        else:
            self._stack_counts.pop(stack_id, None)
            self._stack_vis_members.pop(stack_id, None)
            self._dirty_sids.add(stack_id)

    def on_theme_changed(self):
        self.wash_item.refresh_color()
        if self.wash_item.scene():
            self.wash_item.update()
        self.sync_all_stack_labels()

    def members_of(self, stack_id: str | None) -> list:
        if not stack_id:
            return []
        raw = [
            it for it in self.scene.items()
            if getattr(it, 'stack_id', None) == stack_id and hasattr(it, 'save_id')
        ]
        return sort_stack_members(raw)

    def all_stack_ids(self) -> set[str]:
        return {
            it.stack_id for it in self.scene.items()
            if getattr(it, 'stack_id', None) and hasattr(it, 'save_id')
        }

    def get_stack_name(self, stack_id: str | None) -> str:
        for it in self.members_of(stack_id):
            if getattr(it, 'stack_name', ''):
                return it.stack_name
        return ''

    def set_stack_name(self, stack_id: str, name: str):
        for it in self.members_of(stack_id):
            it.stack_name = name
            it.update()
        self.scene.invalidate_bounds_cache()
        self.sync_stack_label(stack_id)

    def get_stack_center(self, stack_id: str) -> QtCore.QPointF:
        """Always read live stack center from its Cover item on the board (never stale)."""
        if self.active_spread_stack_id == stack_id and (
                self._has_spread_center or not self.spread_center.isNull()):
            return QtCore.QPointF(self.spread_center)
        members = self.members_of(stack_id)
        if not members:
            return QtCore.QPointF(0.0, 0.0)
        c = members[0].center_scene_coords
        self._stack_centers[stack_id] = QtCore.QPointF(c)
        return QtCore.QPointF(c)

    def set_stack_center(self, stack_id: str, center: QtCore.QPointF):
        self._stack_centers[stack_id] = QtCore.QPointF(center)

    def on_items_added_or_removed(self):
        """Ensure every stack retains a valid visible Cover after any delete/undo."""
        self.invalidate_stack_cache()
        for sid in self.all_stack_ids():
            self.ensure_single_cover(sid)
            members = self.members_of(sid)
            if len(members) == 1:
                sole = members[0]
                sole.stack_id = None
                sole.is_stack_cover = False
                sole.stack_name = ''
                sole.stack_saved_scale = None
                sole.stack_saved_rot = None
                sole.setVisible(True)
                sole.update()
            elif len(members) >= 2 and self.active_spread_stack_id != sid:
                if not members[0].isVisible():
                    self.apply_collapsed_pile(sid, animate=False, pop=False)
        self.invalidate_stack_cache()
        self.sync_all_stack_labels()

    def ensure_single_cover(self, stack_id: str):
        members = self.members_of(stack_id)
        if not members:
            return
        chosen = next((it for it in members if it.is_stack_cover), members[0])
        for idx, it in enumerate(members):
            it.is_stack_cover = (it is chosen)
            if it is not chosen and getattr(it, 'stack_order', 0) == 0:
                it.stack_order = idx

    def rebuild_loaded_stacks(self):
        """Re-apply collapsed pile visual state after loading a .bee project."""
        self.invalidate_stack_cache()
        for sid in self.all_stack_ids():
            self.ensure_single_cover(sid)
            members = self.members_of(sid)
            if len(members) < 2:
                for it in members:
                    it.stack_id = None
                    it.is_stack_cover = False
                continue
            center = members[0].center_scene_coords
            self._stack_centers[sid] = QtCore.QPointF(center)
            self.apply_collapsed_pile(sid, center=center, animate=False, pop=False)
        self.invalidate_stack_cache()
        self.sync_all_stack_labels()

    @staticmethod
    def _pos_for_center_and_transform(item, target_center: QtCore.QPointF, scale: float, rot_deg: float) -> QtCore.QPointF:
        """Compute item.pos() so that item.center maps to `target_center` after `scale` & `rot_deg`."""
        t = QtGui.QTransform()
        t.rotate(rot_deg)
        t.scale(scale * item.flip(), scale)
        mapped_local_center = t.map(item.center)
        return target_center - mapped_local_center

    def apply_collapsed_pile(
        self,
        stack_id: str,
        center: QtCore.QPointF | None = None,
        animate: bool = True,
        pop: bool = False,
        collapse_mode: bool = False,
    ):
        """Arrange members of `stack_id` into a physical postcard pile with Cover on top."""
        members = self.members_of(stack_id)
        if not members:
            self._remove_label_item(stack_id)
            return
        self.ensure_single_cover(stack_id)
        members = self.members_of(stack_id)
        self.cancel_flights_for(members)

        if center is None:
            center = self.get_stack_center(stack_id)
        else:
            self._stack_centers[stack_id] = QtCore.QPointF(center)

        cover = members[0]
        for it in members:
            if getattr(it, 'stack_saved_scale', None) is None:
                it.stack_saved_scale = it.scale()
            if getattr(it, 'stack_saved_rot', None) is None:
                it.stack_saved_rot = it.rotation()

        cov_scale = cover.stack_saved_scale or cover.scale()
        cov_w = max(16.0, cover.width * cov_scale)
        cov_h = max(16.0, cover.height * cov_scale)
        cov_geom = math.sqrt(cov_w * cov_h)
        max_cov_edge = max(cov_w, cov_h)

        total_n = len(members)
        non_covers = members[1:]
        m_cnt = len(non_covers)
        if m_cnt <= MAX_VISIBLE_UNDERLAYS:
            chosen_underlay_set = {id(it): i for i, it in enumerate(non_covers)}
        else:
            # Sample representative cards evenly from start to end of the group
            picked = []
            seen_u = set()
            for k in range(MAX_VISIBLE_UNDERLAYS):
                u_idx = round(k * (m_cnt - 1) / max(1, MAX_VISIBLE_UNDERLAYS - 1))
                cand = non_covers[u_idx]
                if id(cand) not in seen_u:
                    seen_u.add(id(cand))
                    picked.append(cand)
            chosen_underlay_set = {id(it): i for i, it in enumerate(picked)}

        underlay_specs = _compute_collage_offsets(
            stack_id, total_n, len(chosen_underlay_set))

        top_z = self.scene.max_z + self.scene.Z_STEP * (total_n + 2)
        self.scene.max_z = top_z

        vis_list = []
        with self.scene.batch_update():
            for idx, it in enumerate(members):
                base_scale = max(1e-4, it.stack_saved_scale or it.scale())
                it_z = top_z - idx * self.scene.Z_STEP
                it.setZValue(it_z)

                if idx == 0:
                    target_scale = base_scale
                    target_rot = 0.0
                    target_center = QtCore.QPointF(center)
                    vis = True
                elif id(it) in chosen_underlay_set:
                    slot_i = chosen_underlay_set[id(it)]
                    dx_r, dy_r, area_mult, tilt_deg = underlay_specs[slot_i]
                    uw = max(1.0, it.width * base_scale)
                    uh = max(1.0, it.height * base_scale)
                    u_geom = math.sqrt(uw * uh)
                    # Normalize visual area so portrait/landscape cards peek naturally on sides/top
                    norm_ratio = (cov_geom * area_mult) / max(1.0, u_geom)
                    cap_ratio = (max_cov_edge * 1.22) / max(uw, uh)
                    target_scale = base_scale * min(norm_ratio, cap_ratio)
                    target_rot = tilt_deg
                    target_center = QtCore.QPointF(
                        center.x() + dx_r * cov_w,
                        center.y() + dy_r * cov_h,
                    )
                    vis = True
                else:
                    uw = max(1.0, it.width * base_scale)
                    uh = max(1.0, it.height * base_scale)
                    target_scale = base_scale * min(
                        1.0, (cov_w * 0.90) / uw, (cov_h * 0.90) / uh)
                    target_rot = 0.0
                    target_center = QtCore.QPointF(center)
                    vis = False

                if vis:
                    vis_list.append(it)

                target_pos = self._pos_for_center_and_transform(
                    it, target_center, target_scale, target_rot)

                if animate and (vis or it.isVisible()):
                    it.setVisible(True)
                    self._start_flight(
                        it,
                        to_pos=target_pos,
                        to_scale=target_scale,
                        to_rot=target_rot,
                        mode='collapse' if collapse_mode else 'spring',
                        hide_after=not vis,
                        trigger_pop=(pop and idx == 0),
                    )
                else:
                    self._flights.pop(it, None)
                    QtWidgets.QGraphicsItem.setRotation(it, target_rot)
                    QtWidgets.QGraphicsItem.setScale(it, target_scale)
                    it.setPos(target_pos)
                    it.setVisible(vis)

        self._stack_counts[stack_id] = total_n
        self._stack_vis_members[stack_id] = vis_list
        self._dirty_sids.discard(stack_id)
        cover.prepareGeometryChange()
        cover.update()
        self.sync_stack_label(stack_id)

    def compute_spread_grid(
        self,
        members: list,
        center: QtCore.QPointF,
    ) -> tuple[dict[object, tuple[QtCore.QPointF, float]], QtCore.QRectF]:
        """Pack `members` around `center` using the Shift+O (`Optimal`) algorithm."""
        n = len(members)
        if n == 0:
            return {}, QtCore.QRectF()

        view = self.scene.views()[0] if self.scene.views() else None
        vscale = max(0.04, view.get_scale() if view else 1.0)
        cfg_gap = float(self.scene.settings.valueOrDefault('Items/arrange_gap') or 0)
        gap = max(cfg_gap, 14.0 / vscale)

        item_dims: list[tuple[float, float, float]] = []
        sizes: list[tuple[int, int]] = []
        for it in members:
            sc = max(1e-4, getattr(it, 'stack_saved_scale', None) or it.scale())
            w = max(20.0, it.width * sc)
            h = max(20.0, it.height * sc)
            item_dims.append((w, h, sc))
            sizes.append((max(1, round(w + gap)), max(1, round(h + gap))))

        if n == 1:
            it = members[0]
            w, h, sc = item_dims[0]
            tpos = self._pos_for_center_and_transform(it, center, sc, 0.0)
            return {it: (tpos, sc)}, QtCore.QRectF(center.x() - w * 0.5, center.y() - h * 0.5, w, h)

        positions, _ = self.scene.pack_optimal_sizes(sizes)
        min_x = min(float(pos[0]) for pos in positions)
        min_y = min(float(pos[1]) for pos in positions)
        max_x = max(float(pos[0]) + w for pos, (w, _h, _sc) in zip(positions, item_dims))
        max_y = max(float(pos[1]) + h for pos, (_w, h, _sc) in zip(positions, item_dims))
        block_cx = (min_x + max_x) * 0.5
        block_cy = (min_y + max_y) * 0.5

        targets: dict[object, tuple[QtCore.QPointF, float]] = {}
        for it, (w, h, sc), pos in zip(members, item_dims, positions):
            cell_center = QtCore.QPointF(
                center.x() + (float(pos[0]) + w * 0.5 - block_cx),
                center.y() + (float(pos[1]) + h * 0.5 - block_cy),
            )
            tpos = self._pos_for_center_and_transform(it, cell_center, sc, 0.0)
            targets[it] = (tpos, sc)

        grid_rect = QtCore.QRectF(
            center.x() + (min_x - block_cx),
            center.y() + (min_y - block_cy),
            max(1.0, max_x - min_x),
            max(1.0, max_y - min_y),
        )
        return targets, grid_rect

    def spread_stack(self, stack_id: str):
        """Open a Collapsed Stack into temporary Spread Grid with Canvas Wash."""
        if self.active_spread_stack_id == stack_id:
            return
        if self.active_spread_stack_id is not None:
            self.collapse_spread_stack(animate=False)

        members = self.members_of(stack_id)
        if len(members) < 2:
            return

        self.scene.cancel_active_modes()
        self.scene.deselect_all_items()
        self.cancel_flights_for(members)

        # Read live Cover position BEFORE setting active_spread_stack_id so
        # get_stack_center never returns a previous session's spread_center!
        center = self.get_stack_center(stack_id)
        self.spread_center = QtCore.QPointF(center)
        self._has_spread_center = True
        self.active_spread_stack_id = stack_id
        self._spread_opened_t0 = time.perf_counter()
        self.sync_stack_label(stack_id)

        targets, grid_rect = self.compute_spread_grid(members, center)
        self.spread_grid_rect = grid_rect
        view = self.scene.views()[0] if self.scene.views() else None
        vscale = max(0.04, view.get_scale() if view else 1.0)
        pad = max(48.0, 48.0 / vscale)
        self.keep_zone = grid_rect.adjusted(-pad, -pad, pad, pad)

        # Activate Canvas Wash right below spread cards and above rest of board
        wash_z = self.scene.max_z + self.scene.Z_STEP * 4
        all_bounds = self.scene.itemsBoundingRect().united(self.keep_zone)
        wash_margin = max(all_bounds.width(), all_bounds.height(), 4000.0) * 3.0
        self.wash_item.refresh_color()
        self.wash_item.setRect(all_bounds.adjusted(
            -wash_margin, -wash_margin, wash_margin, wash_margin))
        self.wash_item.setZValue(wash_z)
        if not self.wash_item.scene():
            self.scene.addItem(self.wash_item)
        self._start_wash(0.80, dur=0.30, hide_on_done=False)

        top_base = wash_z + self.scene.Z_STEP * 2
        with self.scene.batch_update():
            for idx, it in enumerate(members):
                it.setVisible(True)
                it.setZValue(top_base + (len(members) - idx) * self.scene.Z_STEP)
                self.scene.max_z = max(self.scene.max_z, it.zValue())
                tpos, tsc = targets[it]
                self._start_flight(
                    it,
                    to_pos=tpos,
                    to_scale=tsc,
                    to_rot=0.0,
                    mode='spread',
                )
                it.update()

    def collapse_spread_stack(self, animate: bool = True):
        """Fold active Spread Grid back into its Collapsed Stack."""
        sid = self.active_spread_stack_id
        if sid is None:
            return
        collapse_center = QtCore.QPointF(self.spread_center)
        self.active_spread_stack_id = None
        self._has_spread_center = False
        self.spread_center = QtCore.QPointF(0.0, 0.0)
        self._dragging_item = None
        self._pulled_out_preview = False

        self._start_wash(0.0, dur=0.22 if animate else 0.01, hide_on_done=True)

        remaining = self.members_of(sid)
        if len(remaining) >= 2:
            self.apply_collapsed_pile(
                sid,
                center=collapse_center,
                animate=animate,
                pop=False,
                collapse_mode=True,
            )
            for it in remaining:
                it.update()
        elif len(remaining) == 1:
            # Auto-dissolve 1-item stack cleanly
            sole = remaining[0]
            sole.stack_id = None
            sole.is_stack_cover = False
            sole.stack_name = ''
            sole.stack_saved_scale = None
            sole.stack_saved_rot = None
            sole.setVisible(True)
            sole.update()
            self.invalidate_stack_cache(sid)
            self.sync_stack_label(sid)
        else:
            self.invalidate_stack_cache(sid)
            self.sync_stack_label(sid)

        self.scene.deselect_all_items()
        if self.scene.views():
            self.scene.views()[0].refresh_contextual_toolbar()

    # --- Live Pull-Out & Reorder during Spread Drag ---

    def begin_spread_drag(self, item):
        self._dragging_item = item
        self._pulled_out_preview = False

    def update_spread_drag(self, item):
        sid = self.active_spread_stack_id
        if not sid or item is not self._dragging_item:
            return

        item_center = item.center_scene_coords
        outside = not self.keep_zone.contains(item_center)

        members = self.members_of(sid)
        others = [m for m in members if m is not item]
        if not others:
            return

        if outside != self._pulled_out_preview:
            self._pulled_out_preview = outside
            if outside:
                # Live Grid Reflow of remaining N-1 items via Spring place (300/30)!
                targets, _ = self.compute_spread_grid(others, self.spread_center)
                for m in others:
                    tpos, tsc = targets[m]
                    self._start_flight(
                        m, to_pos=tpos, to_scale=tsc, to_rot=0.0, mode='spring')
            else:
                targets, _ = self.compute_spread_grid(members, self.spread_center)
                for m in others:
                    tpos, tsc = targets[m]
                    self._start_flight(
                        m, to_pos=tpos, to_scale=tsc, to_rot=0.0, mode='spring')

    def finish_spread_drag(self, item, orig_pos: QtCore.QPointF) -> bool:
        """Finalize drag in Spread mode. Returns True if handled as Pull-Out / Snap."""
        sid = self.active_spread_stack_id
        if not sid or item is not self._dragging_item:
            self._dragging_item = None
            return False

        was_outside = self._pulled_out_preview
        self._dragging_item = None
        self._pulled_out_preview = False

        if was_outside:
            from beeref import commands
            final_pos = QtCore.QPointF(item.pos())
            # Temporarily restore item to orig_pos so Undo records clean pre-drag state
            item.setPos(orig_pos)
            self.scene.undo_stack.push(
                commands.PullOutFromStackCommand(self.scene, sid, item, final_pos))
            return True

        # Snap dragged item back cleanly into its Spread Grid cell
        members = self.members_of(sid)
        targets, grid_rect = self.compute_spread_grid(members, self.spread_center)
        self.spread_grid_rect = grid_rect
        if item in targets:
            tpos, tsc = targets[item]
            self._start_flight(
                item, to_pos=tpos, to_scale=tsc, to_rot=0.0, mode='spring')
        return True

    def refresh_active_spread_layout(self):
        """Reflow currently open Spread Grid (e.g. after Cover change or item delete)."""
        self.invalidate_stack_cache(self.active_spread_stack_id)
        sid = self.active_spread_stack_id
        if not sid:
            return
        members = self.members_of(sid)
        if len(members) < 2:
            self.collapse_spread_stack(animate=True)
            return
        targets, grid_rect = self.compute_spread_grid(members, self.spread_center)
        self.spread_grid_rect = grid_rect
        view = self.scene.views()[0] if self.scene.views() else None
        vscale = max(0.04, view.get_scale() if view else 1.0)
        pad = max(48.0, 48.0 / vscale)
        self.keep_zone = grid_rect.adjusted(-pad, -pad, pad, pad)
        for m in members:
            tpos, tsc = targets[m]
            self._start_flight(
                m, to_pos=tpos, to_scale=tsc, to_rot=0.0, mode='spring')
            m.update()

    # --- Internal 120 FPS Animation Driver ---

    def _start_wash(self, target_opacity: float, dur: float, hide_on_done: bool):
        self._wash_from = self.wash_item.opacity()
        self._wash_to = target_opacity
        self._wash_t0 = time.perf_counter()
        self._wash_dur = max(0.01, dur)
        self._wash_hide_on_done = hide_on_done
        self._timer.start()

    def _start_flight(
        self,
        item,
        to_pos: QtCore.QPointF,
        to_scale: float,
        to_rot: float,
        mode: str = 'spring',
        hide_after: bool = False,
        trigger_pop: bool = False,
    ):
        self._flights[item] = {
            'from_pos': QtCore.QPointF(item.pos()),
            'to_pos': QtCore.QPointF(to_pos),
            'from_scale': item.scale(),
            'to_scale': to_scale,
            'from_rot': item.rotation(),
            'to_rot': to_rot,
            't0': time.perf_counter(),
            'mode': mode,
            'hide_after': hide_after,
            'trigger_pop': trigger_pop,
        }
        self._timer.start()

    def _on_tick(self):
        now = time.perf_counter()
        active = False
        touched_sids: set[str] = set()

        # 1. Canvas Wash fade
        if self.wash_item.scene():
            dt_w = now - self._wash_t0
            if dt_w < self._wash_dur:
                u = cubic_bezier(0.25, 0.1, 0.25, 1.0, dt_w / self._wash_dur)
                self.wash_item.setOpacity(
                    self._wash_from + (self._wash_to - self._wash_from) * u)
                active = True
            else:
                self.wash_item.setOpacity(self._wash_to)
                if self._wash_hide_on_done and self.wash_item.scene():
                    self._wash_hide_on_done = False
                    self.scene.removeItem(self.wash_item)

        # 2. Item flights
        done_items = []
        if self._flights:
            with self.scene.batch_update():
                for item, st in list(self._flights.items()):
                    if item.scene() is None:
                        done_items.append(item)
                        continue
                    sid = getattr(item, 'stack_id', None)
                    if sid and self.active_spread_stack_id != sid:
                        touched_sids.add(sid)

                    dt = now - st['t0']
                    mode = st['mode']
                    if mode == 'spread':
                        dur = 0.50
                        raw = min(1.0, dt / dur)
                        f = spread_flight_factor(raw)
                        finished = (dt >= dur)
                    elif mode == 'collapse':
                        dur = 0.24
                        raw = min(1.0, dt / dur)
                        f = collapse_flight_factor(raw)
                        finished = (dt >= dur)
                    else:
                        dur = SPRING_PLACE.settle_duration
                        f = SPRING_PLACE.value(dt)
                        finished = (dt >= dur)

                    if finished:
                        f = 1.0

                    cur_rot = st['from_rot'] + (st['to_rot'] - st['from_rot']) * f
                    cur_sc = st['from_scale'] + (st['to_scale'] - st['from_scale']) * f
                    cur_pos = (
                        st['from_pos'] + (st['to_pos'] - st['from_pos']) * f
                    )
                    item.prepareGeometryChange()
                    QtWidgets.QGraphicsItem.setRotation(item, cur_rot)
                    QtWidgets.QGraphicsItem.setScale(item, cur_sc)
                    item.setPos(cur_pos)

                    if finished:
                        if st['hide_after']:
                            item.setVisible(False)
                        if st['trigger_pop']:
                            self._pop_targets = [(item, st['to_scale'])]
                            self._pop_t0 = now
                        done_items.append(item)
                    else:
                        active = True

            for it in done_items:
                self._flights.pop(it, None)

        # 3. Spring pop bump (420/14: scale 1.06 -> 1.0 around center)
        if self._pop_t0 > 0 and self._pop_targets:
            dt_p = now - self._pop_t0
            if dt_p < 0.55:
                prog_p = SPRING_POP.value(dt_p)
                mult = 1.06 + (1.0 - 1.06) * prog_p
                for item, base_sc in self._pop_targets:
                    if item.scene() is not None:
                        sid = getattr(item, 'stack_id', None)
                        if sid and self.active_spread_stack_id != sid:
                            touched_sids.add(sid)
                        c = item.center_scene_coords
                        tpos = self._pos_for_center_and_transform(
                            item, c, base_sc * mult, item.rotation())
                        QtWidgets.QGraphicsItem.setScale(item, base_sc * mult)
                        item.setPos(tpos)
                active = True
            else:
                for item, base_sc in self._pop_targets:
                    if item.scene() is not None:
                        sid = getattr(item, 'stack_id', None)
                        if sid and self.active_spread_stack_id != sid:
                            touched_sids.add(sid)
                        c = item.center_scene_coords
                        tpos = self._pos_for_center_and_transform(
                            item, c, base_sc, item.rotation())
                        QtWidgets.QGraphicsItem.setScale(item, base_sc)
                        item.setPos(tpos)
                self._pop_targets.clear()
                self._pop_t0 = -1.0

        for sid in touched_sids:
            self.sync_stack_label(sid)

        if not active:
            self._timer.stop()
            self.sync_all_stack_labels()


def new_stack_id() -> str:
    return uuid.uuid4().hex[:12]
