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

from contextlib import contextmanager
from functools import partial
import heapq
import logging
import math
from queue import Empty, Queue
import time

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtCore import Qt

import rpack

from beeref import commands
from beeref.config import BeeSettings
from beeref.deskboard_motion import Spring
from beeref.items import item_registry, BeeErrorItem, sort_by_filename
from beeref.lod_cache import LODCacheManager
from beeref.selection import MultiSelectItem, RubberbandItem
from beeref.stack_manager import StackManager, new_stack_id


logger = logging.getLogger(__name__)
_SPRING_HOVER_LIFT = Spring(420.0, 26.0)


def _pack_large_masonry(sizes: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """O(N log K) tight masonry column packer for 300 - 20,000+ images.

    Packs thousands of heterogeneous rectangles into a balanced ~square
    bounding box in < 5ms (avoiding rpack's O(N^2.5) freeze on 1000+ items).
    """
    n = len(sizes)
    if n == 0:
        return []
    total_area = sum(max(1, w) * max(1, h) for w, h in sizes)
    avg_w = sum(max(1, w) for w, _ in sizes) / n
    target_side = max(avg_w, math.sqrt(total_area * 1.05))
    num_cols = max(2, round(target_side / max(1.0, avg_w)))

    # Sort tallest/widest items slightly earlier while keeping natural locality,
    # or pack greedily into shortest column: track column widths and heights.
    # Two-pass column layout: assign items to columns via min-heap of heights,
    # then compute exact x-offset of each column from its widest item!
    col_items: list[list[int]] = [[] for _ in range(num_cols)]
    # heap entries: (current_col_height, col_index)
    heap = [(0, c) for c in range(num_cols)]
    heapq.heapify(heap)

    for idx, (_w, h) in enumerate(sizes):
        cur_h, col = heapq.heappop(heap)
        col_items[col].append(idx)
        heapq.heappush(heap, (cur_h + h, col))

    positions: list[tuple[int, int]] = [(0, 0)] * n
    cur_x = 0
    for col in range(num_cols):
        indices = col_items[col]
        if not indices:
            continue
        col_w = max(sizes[i][0] for i in indices)
        cur_y = 0
        for i in indices:
            w, h = sizes[i]
            # Center horizontally within column
            px = cur_x + (col_w - w) // 2
            positions[i] = (px, cur_y)
            cur_y += h
        cur_x += col_w

    return positions


class BeeGraphicsScene(QtWidgets.QGraphicsScene):
    cursor_changed = QtCore.pyqtSignal(QtGui.QCursor)
    cursor_cleared = QtCore.pyqtSignal()

    MOVE_MODE = 1
    RUBBERBAND_MODE = 2

    def __init__(self, undo_stack):
        super().__init__()
        # Deeper BSP spatial index keeps frustum culling & hit-testing O(log N)
        # even when 2,000 - 10,000 items are on the board.
        self.setItemIndexMethod(
            QtWidgets.QGraphicsScene.ItemIndexMethod.BspTreeIndex)
        self.setBspTreeDepth(12)

        self.active_mode = None
        self.undo_stack = undo_stack
        self.max_z = 0
        self.min_z = 0
        self.Z_STEP = 0.001

        self._batch_depth = 0
        self._batch_dirty_change = False
        self._batch_dirty_selection = False
        self._cached_all_bounds: QtCore.QRectF | None = None
        self._cached_sel_bounds: QtCore.QRectF | None = None
        self._pending_insert_items: list = []
        self._expanding_stack_sel = False

        # Stack Group gesture tracking
        self._pressed_collapsed_sid: str | None = None
        self._collapsed_dragged = False
        self._spread_press_item = None
        self._spread_press_orig_pos = QtCore.QPointF()
        self._spread_dragged = False
        self.stack_manager = StackManager(self)

        # Zero-overhead shared hover micro-bounce animator
        self._hovered_targets: set = set()
        self._hover_anim_items: set = set()
        self._hover_timer = QtCore.QTimer(self)
        self._hover_timer.setInterval(8)  # 120 FPS
        self._hover_timer.timeout.connect(self._on_hover_tick)

        self.selectionChanged.connect(self.on_selection_change)
        self.changed.connect(self.on_change)
        self.items_to_add = Queue()
        self.edit_item = None
        self.crop_item = None
        self.settings = BeeSettings()
        self._clear_ongoing = False
        self.clear()

    @property
    def in_batch_update(self) -> bool:
        return self._batch_depth > 0

    def invalidate_bounds_cache(self):
        self._cached_all_bounds = None
        self._cached_sel_bounds = None

    @contextmanager
    def batch_update(self):
        """Suppress O(N^2) scene/selection recomputations during bulk edits."""
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                self.invalidate_bounds_cache()
                if self._batch_dirty_selection:
                    self._batch_dirty_selection = False
                    self.on_selection_change()
                    for v in self.views():
                        if hasattr(v, 'on_selection_changed'):
                            v.on_selection_changed()
                if self._batch_dirty_change:
                    self._batch_dirty_change = False
                    self.on_change([])
                    for v in self.views():
                        if hasattr(v, 'on_scene_changed'):
                            v.on_scene_changed([])

    def clear(self):
        self._clear_ongoing = True
        if hasattr(self, '_hover_timer'):
            self._hover_timer.stop()
            self._hovered_targets.clear()
            self._hover_anim_items.clear()
        LODCacheManager.instance().clear_all()
        if hasattr(self, 'stack_manager'):
            self.stack_manager.clear()
        super().clear()
        self.internal_clipboard = []
        self._pending_insert_items = []
        self.rubberband_item = RubberbandItem()
        self.multi_select_item = MultiSelectItem()
        self.invalidate_bounds_cache()
        self._clear_ongoing = False

    def on_item_hover_changed(self, item, entered: bool):
        if self._clear_ongoing:
            return
        if entered:
            if self.active_mode is not None:
                return
            view = self.views()[0] if self.views() else None
            if view is not None and getattr(view, 'active_mode', None) is not None:
                return
        elif not self._hovered_targets and not self._hover_anim_items:
            return

        new_targets: set = set()
        if entered:
            sid = getattr(item, 'stack_id', None)
            if sid and self.stack_manager.active_spread_stack_id != sid:
                new_targets = set(self.stack_manager.visible_pile_members_fast(sid))
            else:
                new_targets = {item}
        else:
            # Check if another card in the same collapsed stack is still hovered
            sid = getattr(item, 'stack_id', None)
            if sid and self.stack_manager.active_spread_stack_id != sid:
                vis_m = self.stack_manager.visible_pile_members_fast(sid)
                if any(getattr(m, '_hover_inside', False) for m in vis_m):
                    new_targets = set(vis_m)

        now = time.perf_counter()
        changed = (new_targets ^ self._hovered_targets)
        for it in changed:
            target = 1.0 if (it in new_targets) else 0.0
            if abs(getattr(it, '_hover_target', 0.0) - target) > 1e-4:
                it._hover_target = target
                it._hover_from = getattr(it, '_hover_lift', 0.0)
                it._hover_t0 = now
                self._hover_anim_items.add(it)

        self._hovered_targets = new_targets
        if self._hover_anim_items and not self._hover_timer.isActive():
            self._hover_timer.start()

    def _on_hover_tick(self):
        if not self._hover_anim_items:
            self._hover_timer.stop()
            return
        now = time.perf_counter()
        done = []
        for it in list(self._hover_anim_items):
            if it.scene() is not self or not it.isVisible():
                it._hover_lift = 0.0
                it._hover_target = 0.0
                done.append(it)
                continue
            dt = now - getattr(it, '_hover_t0', now)
            target = getattr(it, '_hover_target', 0.0)
            start = getattr(it, '_hover_from', 0.0)
            if target > 0.5:
                dur = 0.28
                prog = _SPRING_HOVER_LIFT.value(dt) if dt < dur else 1.0
            else:
                dur = 0.16
                u = min(1.0, dt / dur)
                prog = 1.0 - (1.0 - u) * (1.0 - u)
            it._hover_lift = start + (target - start) * prog
            it.update()
            if dt >= dur:
                it._hover_lift = target
                done.append(it)

        for it in done:
            self._hover_anim_items.discard(it)
        if not self._hover_anim_items:
            self._hover_timer.stop()

    def addItem(self, item):
        self.invalidate_bounds_cache()
        super().addItem(item)

    def removeItem(self, item):
        if getattr(item, 'is_image', False):
            LODCacheManager.instance().evict_item(item)
        self.invalidate_bounds_cache()
        super().removeItem(item)

    def cancel_active_modes(self):
        self.cancel_crop_mode()
        self.end_rubberband_mode()

    def end_rubberband_mode(self):
        if self.rubberband_item.scene():
            self.removeItem(self.rubberband_item)
        self.active_mode = None

    def cancel_crop_mode(self):
        if self.crop_item:
            self.crop_item.exit_crop_mode(confirm=False)

    def copy_selection_to_internal_clipboard(self):
        self.internal_clipboard = list(self.selectedItems(user_only=True))

    def paste_from_internal_clipboard(self, position):
        copies = [item.create_copy() for item in self.internal_clipboard]
        self.undo_stack.push(commands.InsertItems(self, copies, position))

    def raise_to_top(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if not items:
            return
        delta = self.max_z + self.Z_STEP - min(i.zValue() for i in items)
        with self.batch_update():
            for item in items:
                item.setZValue(item.zValue() + delta)

    def lower_to_bottom(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if not items:
            return
        delta = self.min_z - self.Z_STEP - max(i.zValue() for i in items)
        with self.batch_update():
            for item in items:
                item.setZValue(item.zValue() + delta)

    def _item_scene_rect_fast(self, item) -> QtCore.QRectF:
        return item.sceneTransform().mapRect(item.bounding_rect_unselected())

    def _arrange_unit_scene_rect(self, item) -> QtCore.QRectF:
        if hasattr(item, '_is_collapsed_stack_cover') and item._is_collapsed_stack_cover():
            return item.sceneTransform().mapRect(item._collapsed_pile_local_rect())
        return self._item_scene_rect_fast(item)

    def normalize_width_or_height(self, mode):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if len(items) < 2:
            return
        dims = [getattr(self._item_scene_rect_fast(item), mode)() for item in items]
        avg = sum(dims) / len(dims)
        scale_factors = [avg / max(1e-6, d) for d in dims]
        self.undo_stack.push(commands.NormalizeItems(items, scale_factors))

    def normalize_height(self):
        return self.normalize_width_or_height('height')

    def normalize_width(self):
        return self.normalize_width_or_height('width')

    def normalize_size(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if len(items) < 2:
            return
        areas = []
        for item in items:
            r = self._item_scene_rect_fast(item)
            areas.append(max(1e-6, r.width() * r.height()))
        avg = sum(areas) / len(areas)
        scale_factors = [math.sqrt(avg / a) for a in areas]
        self.undo_stack.push(commands.NormalizeItems(items, scale_factors))

    def arrange_default(self):
        default = self.settings.valueOrDefault('Items/arrange_default')
        MAPPING = {
            'optimal': self.arrange_optimal,
            'horizontal': self.arrange,
            'vertical': partial(self.arrange, vertical=True),
            'square': self.arrange_square,
        }
        MAPPING[default]()

    def _collapse_stack_units_for_arrange(self, items: list) -> list:
        """Represent each selected Collapsed Stack by its single Cover item."""
        if self.stack_manager.active_spread_stack_id is not None:
            return list(items)
        out = []
        seen_sids = set()
        for it in items:
            sid = getattr(it, 'stack_id', None)
            if sid:
                if sid not in seen_sids:
                    seen_sids.add(sid)
                    members = self.stack_manager.members_of(sid)
                    out.append(members[0] if members else it)
            else:
                out.append(it)
        return out

    def arrange(self, vertical=False):
        """Arrange items in a line (horizontally or vertically)."""
        self.cancel_active_modes()
        raw_items = self._collapse_stack_units_for_arrange(
            self.selectedItems(user_only=True))
        items = sort_by_filename(raw_items)
        if len(items) < 2:
            return

        gap = self.settings.valueOrDefault('Items/arrange_gap')
        center = self.get_selection_center()
        positions = []
        rects = [
            {'rect': self._item_scene_rect_fast(item), 'item': item}
            for item in items
        ]

        if vertical:
            rects.sort(key=lambda r: r['rect'].topLeft().y())
            sum_height = sum(r['rect'].height() for r in rects)
            y = round(center.y() - sum_height / 2)
            for rect in rects:
                positions.append(
                    QtCore.QPointF(
                        round(center.x() - rect['rect'].width() / 2), y))
                y += rect['rect'].height() + gap
        else:
            rects.sort(key=lambda r: r['rect'].topLeft().x())
            sum_width = sum(r['rect'].width() for r in rects)
            x = round(center.x() - sum_width / 2)
            for rect in rects:
                positions.append(
                    QtCore.QPointF(
                        x, round(center.y() - rect['rect'].height() / 2)))
                x += rect['rect'].width() + gap

        self.undo_stack.push(
            commands.ArrangeItems(
                self, [r['item'] for r in rects], positions))

    def pack_optimal_sizes(
        self,
        sizes: list[tuple[int, int]],
    ) -> tuple[list[tuple[int, int]], tuple[int, int]]:
        """Pack (w, h) rectangles into a compact Optimal block (zero orphan rows)."""
        n = len(sizes)
        if n == 0:
            return [], (0, 0)
        if n == 1:
            return [(0, 0)], sizes[0]
        if n > 300:
            positions = _pack_large_masonry(sizes)
            max_x = max(p[0] + s[0] for p, s in zip(positions, sizes))
            max_y = max(p[1] + s[1] for p, s in zip(positions, sizes))
            return positions, (max_x, max_y)

        min_area = sum(s[0] * s[1] for s in sizes)
        max_single_w = max(s[0] for s in sizes)
        max_single_h = max(s[1] for s in sizes)
        avg_w = sum(s[0] for s in sizes) / n
        avg_h = sum(s[1] for s in sizes) / n

        candidates: list[tuple[float, list[tuple[int, int]], tuple[int, int]]] = []

        w_grid = math.ceil(round(math.sqrt(n)) * avg_w * 1.005)
        w_cols_ceil = math.ceil(math.ceil(math.sqrt(n)) * avg_w * 1.005)
        w_area_sq = math.ceil(math.sqrt(min_area) * 1.04)
        w_area_ratio = math.ceil(math.sqrt(min_area * avg_w / max(1.0, avg_h)) * 1.03)

        base_widths = {
            max(max_single_w, w_grid),
            max(max_single_w, w_cols_ceil),
            max(max_single_w, w_area_sq),
            max(max_single_w, math.ceil(math.sqrt(min_area) * 1.18)),
            max(max_single_w, math.ceil(math.sqrt(min_area) * 1.32)),
            max(max_single_w, w_area_ratio),
        }
        for w0 in base_widths:
            w_try = max(max_single_w, w0)
            h_limit = max(
                max_single_h,
                math.ceil((min_area / max(1, w_try)) * 1.28),
            )
            for _ in range(10):
                try:
                    pos = rpack.pack(sizes, max_width=w_try, max_height=h_limit)
                    bounds = rpack.bbox_size(sizes, pos)
                    bw, bh = bounds[0], bounds[1]
                    ar_penalty = 1.0 + 0.22 * abs(math.log(max(1.0, bw) / max(1.0, bh)))
                    score = float(bw * bh) * ar_penalty
                    candidates.append((score, pos, bounds))
                    break
                except rpack.PackingImpossibleError:
                    h_limit = math.ceil(h_limit * 1.10)
                    w_try = math.ceil(w_try * 1.04)

        if not candidates:
            pos = rpack.pack(sizes)
            bounds = rpack.bbox_size(sizes, pos)
            return pos, bounds

        candidates.sort(key=lambda x: x[0])
        _, best_pos, best_bounds = candidates[0]
        return best_pos, best_bounds

    def compute_optimal_positions(self, items, gap: int | None = None):
        """Compute (ordered_items, qpositions) for Optimal square/rect packing."""
        items = self._collapse_stack_units_for_arrange(items)
        if len(items) < 2:
            return list(items), [i.pos() for i in items]

        if gap is None:
            gap = self.settings.valueOrDefault('Items/arrange_gap')

        ordered = list(items) if len(items) <= 300 else sort_by_filename(items)
        unpadded_rects = [self._arrange_unit_scene_rect(item) for item in ordered]
        sizes = [
            (
                max(1, round(rect.width() + gap)),
                max(1, round(rect.height() + gap)),
            )
            for rect in unpadded_rects
        ]

        positions, _ = self.pack_optimal_sizes(sizes)
        min_x = min(p[0] for p in positions)
        min_y = min(p[1] for p in positions)
        max_x = max(p[0] + r.width() for p, r in zip(positions, unpadded_rects))
        max_y = max(p[1] + r.height() for p, r in zip(positions, unpadded_rects))
        packed_center = QtCore.QPointF((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
        center = self.get_selection_center()
        diff = center - packed_center
        qpositions = [QtCore.QPointF(p[0], p[1]) + diff for p in positions]
        return ordered, qpositions

    def arrange_optimal(self):
        self.cancel_active_modes()
        items = self._collapse_stack_units_for_arrange(
            self.selectedItems(user_only=True))
        if len(items) < 2:
            return
        ordered, qpositions = self.compute_optimal_positions(items)
        self.undo_stack.push(commands.ArrangeItems(self, ordered, qpositions))

    def arrange_square(self):
        self.cancel_active_modes()
        gap = self.settings.valueOrDefault('Items/arrange_gap')
        raw_items = self._collapse_stack_units_for_arrange(
            self.selectedItems(user_only=True))
        items = sort_by_filename(raw_items)
        if len(items) < 2:
            return

        rects = [self._item_scene_rect_fast(item) for item in items]
        max_width = max(r.width() + gap for r in rects)
        max_height = max(r.height() + gap for r in rects)

        num_rows = math.ceil(math.sqrt(len(items)))
        center = self.get_selection_center()
        diff = center - (num_rows / 2) * QtCore.QPointF(max_width, max_height)

        positions = []
        idx = 0
        n = len(items)
        for j in range(num_rows):
            for i in range(num_rows):
                if idx >= n:
                    break
                r = rects[idx]
                point = QtCore.QPointF(
                    i * max_width + (max_width - r.width()) / 2,
                    j * max_height + (max_height - r.height()) / 2,
                )
                positions.append(point + diff)
                idx += 1

        self.undo_stack.push(commands.ArrangeItems(self, items, positions))

    def flip_items(self, vertical=False):
        self.cancel_active_modes()
        self.undo_stack.push(
            commands.FlipItems(self.selectedItems(user_only=True),
                               self.get_selection_center(),
                               vertical=vertical))

    def crop_items(self):
        if self.crop_item:
            return
        if self.has_single_image_selection():
            item = self.selectedItems(user_only=True)[0]
            if item.is_image:
                item.enter_crop_mode()

    def sample_color_at(self, position):
        for cand in self.items(
            position,
            Qt.ItemSelectionMode.IntersectsItemShape,
            Qt.SortOrder.DescendingOrder,
            self.views()[0].transform(),
        ):
            if hasattr(cand, 'sample_color_at') and cand.isVisible():
                return cand.sample_color_at(position)

    def select_all_items(self):
        self.cancel_active_modes()
        with self.batch_update():
            for item in self.items():
                if hasattr(item, 'save_id') and item.isVisible():
                    item.setSelected(True)

    def deselect_all_items(self):
        self.cancel_active_modes()
        with self.batch_update():
            self.clearSelection()

    def _count_selected_up_to(self, limit: int) -> int:
        count = 0
        for item in super().selectedItems():
            if hasattr(item, 'save_id'):
                count += 1
                if count >= limit:
                    return count
        return count

    def has_selection(self):
        """O(1) check whether at least 1 user item is selected."""
        return self._count_selected_up_to(1) >= 1

    def has_single_selection(self):
        """O(1) check whether exactly 1 user item is selected."""
        return self._count_selected_up_to(2) == 1

    def has_multi_selection(self):
        """O(1) check whether 2+ user items are selected."""
        return self._count_selected_up_to(2) >= 2

    def has_single_image_selection(self):
        if not self.has_single_selection():
            return False
        for item in super().selectedItems():
            if hasattr(item, 'save_id'):
                return getattr(item, 'is_image', False)
        return False

    def create_stack_from_selection(self) -> str | None:
        self.cancel_active_modes()
        if self.stack_manager.active_spread_stack_id is not None:
            self.stack_manager.collapse_spread_stack(animate=False)
        items = [
            it for it in self.selectedItems(user_only=True)
            if getattr(it, 'is_image', False)
        ]
        # Also pull in any hidden members of already-selected collapsed stacks
        seen_ids = {id(it) for it in items}
        for it in list(items):
            if getattr(it, 'stack_id', None):
                for m in self.stack_manager.members_of(it.stack_id):
                    if id(m) not in seen_ids:
                        seen_ids.add(id(m))
                        items.append(m)

        if len(items) < 2:
            return None

        center = self.get_selection_center()
        sid = new_stack_id()
        self.undo_stack.push(
            commands.CreateStackCommand(self, items, sid, center))
        return sid

    def unstack_selection(self) -> bool:
        self.cancel_active_modes()
        sids = set()
        if self.stack_manager.active_spread_stack_id:
            sids.add(self.stack_manager.active_spread_stack_id)
        for it in self.selectedItems(user_only=True):
            if getattr(it, 'stack_id', None):
                sids.add(it.stack_id)
        if not sids:
            return False
        self.undo_stack.beginMacro('Unstack Groups')
        for sid in sids:
            self.undo_stack.push(commands.UnstackCommand(self, sid))
        self.undo_stack.endMacro()
        return True

    def selected_single_stack_id(self) -> str | None:
        """If selection corresponds to exactly 1 collapsed Stack Group, return its stack_id."""
        if self.stack_manager.active_spread_stack_id is not None:
            return None
        sel = self.selectedItems(user_only=True)
        if not sel:
            return None
        sids = {getattr(it, 'stack_id', None) for it in sel}
        if len(sids) == 1:
            sid = next(iter(sids))
            if sid:
                return sid
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self.event_start = event.scenePos()
            view = self.views()[0]
            self._event_start_screen = view.mapFromScene(event.scenePos())
            self._pressed_collapsed_sid = None
            self._collapsed_dragged = False
            self._spread_press_item = None
            self._spread_dragged = False

            item_at_pos = self.itemAt(event.scenePos(), view.transform())
            if (item_at_pos is not None
                    and not hasattr(item_at_pos, 'save_id')
                    and item_at_pos is not self.multi_select_item
                    and item_at_pos is not self.stack_manager.wash_item):
                item_at_pos = None
                for cand in self.items(
                    event.scenePos(),
                    Qt.ItemSelectionMode.IntersectsItemShape,
                    Qt.SortOrder.DescendingOrder,
                    view.transform(),
                ):
                    if (cand is self.multi_select_item
                            or cand is self.stack_manager.wash_item
                            or (hasattr(cand, 'save_id') and cand.isVisible())):
                        item_at_pos = cand
                        break

            # Resolve MultiSelectItem down to corner handle, underlying user item, or empty gap!
            if item_at_pos is self.multi_select_item:
                if (not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                        and self.multi_select_item.hit_handle_at_scene_pos(event.scenePos())):
                    item_at_pos = self.multi_select_item
                else:
                    found_user = None
                    for cand in self.items(
                        event.scenePos(),
                        Qt.ItemSelectionMode.IntersectsItemShape,
                        Qt.SortOrder.DescendingOrder,
                        view.transform(),
                    ):
                        if hasattr(cand, 'save_id') and cand.isVisible():
                            found_user = cand
                            break
                    if found_user is not None:
                        item_at_pos = found_user
                    else:
                        # Clicked in an empty gap inside multi_select_item or outside actual cards -> start rubberband!
                        item_at_pos = None
                        if not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                            self.deselect_all_items()
                        self.active_mode = self.RUBBERBAND_MODE
                        event.accept()
                        return

            # --- Case A: Active Spread Session ---
            active_sid = self.stack_manager.active_spread_stack_id
            if active_sid is not None:
                if (item_at_pos is None
                        or item_at_pos is self.stack_manager.wash_item
                        or getattr(item_at_pos, 'stack_id', None) != active_sid):
                    if not self.stack_manager.can_dismiss_spread_by_wash():
                        event.accept()
                        return
                    self.stack_manager.collapse_spread_stack(animate=True)
                    event.accept()
                    return

                # Check 1-click Cover Badge on top-left of Spread card
                local_pt = item_at_pos.mapFromScene(event.scenePos())
                if hasattr(item_at_pos, 'hit_spread_cover_badge') and item_at_pos.hit_spread_cover_badge(local_pt):
                    if not item_at_pos.is_stack_cover:
                        self.undo_stack.push(
                            commands.SetStackCoverCommand(self, active_sid, item_at_pos))
                    if hasattr(view, 'show_toast'):
                        view.show_toast('Đã đặt làm hình đại diện nhóm')
                    event.accept()
                    return

                with self.batch_update():
                    self.clearSelection()
                    item_at_pos.setSelected(True)
                    item_at_pos.bring_to_front()
                self._spread_press_item = item_at_pos
                self._spread_press_orig_pos = QtCore.QPointF(item_at_pos.pos())
                self.stack_manager.begin_spread_drag(item_at_pos)
                self.active_mode = self.MOVE_MODE
                super().mousePressEvent(event)
                return

            # --- Case B: Normal Board Mode ---
            if self.edit_item:
                if item_at_pos != self.edit_item:
                    self.edit_item.exit_edit_mode()
                else:
                    super().mousePressEvent(event)
                    return
            if self.crop_item:
                if item_at_pos != self.crop_item:
                    self.cancel_crop_mode()
                else:
                    super().mousePressEvent(event)
                    return

            if item_at_pos and hasattr(item_at_pos, 'save_id'):
                sid = getattr(item_at_pos, 'stack_id', None)
                if sid:
                    self._pressed_collapsed_sid = sid
                    ctrl_held = bool(
                        event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                    if ctrl_held:
                        new_state = not item_at_pos.isSelected()
                        with self.batch_update():
                            for m in self.stack_manager.members_of(sid):
                                m.setSelected(new_state and m.isVisible())
                        event.accept()
                        return
                    if not item_at_pos.isSelected():
                        with self.batch_update():
                            self.clearSelection()
                            for m in self.stack_manager.members_of(sid):
                                if m.isVisible():
                                    m.setSelected(True)
                self.active_mode = self.MOVE_MODE
            elif item_at_pos:
                self.active_mode = self.MOVE_MODE
            elif self.items():
                if not (event.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier
                )):
                    self.deselect_all_items()
                self.active_mode = self.RUBBERBAND_MODE

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.cancel_active_modes()
        view = self.views()[0]
        item = self.itemAt(event.scenePos(), view.transform())
        if (item is not None
                and not hasattr(item, 'save_id')
                and item is not self.multi_select_item):
            item = None
            for cand in self.items(
                event.scenePos(),
                Qt.ItemSelectionMode.IntersectsItemShape,
                Qt.SortOrder.DescendingOrder,
                view.transform(),
            ):
                if cand is self.multi_select_item or (hasattr(cand, 'save_id') and cand.isVisible()):
                    item = cand
                    break
        if item is self.multi_select_item:
            resolved = None
            for cand in self.items(
                event.scenePos(),
                Qt.ItemSelectionMode.IntersectsItemShape,
                Qt.SortOrder.DescendingOrder,
                view.transform(),
            ):
                if hasattr(cand, 'save_id') and cand.isVisible():
                    resolved = cand
                    break
            if resolved is not None:
                item = resolved
            elif self.selected_single_stack_id():
                sid = self.selected_single_stack_id()
                self.stack_manager.spread_stack(sid)
                view.refresh_contextual_toolbar()
                event.accept()
                return

        if item and hasattr(item, 'save_id'):
            sid = getattr(item, 'stack_id', None)
            if sid and self.stack_manager.active_spread_stack_id is None:
                self.stack_manager.spread_stack(sid)
                view.refresh_contextual_toolbar()
                event.accept()
                return
            if not item.isSelected():
                item.setSelected(True)
            if item.is_editable:
                item.enter_edit_mode()
                self.mousePressEvent(event)
            elif getattr(item, 'is_image', False):
                view.open_detail_stage(item)
            else:
                view.fit_rect(
                    self._item_scene_rect_fast(item),
                    toggle_item=item)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        view = self.views()[0]
        if hasattr(self, '_event_start_screen'):
            cur_scr = view.mapFromScene(event.scenePos())
            moved_px = (cur_scr - self._event_start_screen).manhattanLength()
        else:
            moved_px = 0

        if self._spread_press_item is not None and moved_px >= 4:
            self._spread_dragged = True
            super().mouseMoveEvent(event)
            self.stack_manager.update_spread_drag(self._spread_press_item)
            return

        if self._pressed_collapsed_sid is not None and moved_px >= 4:
            self._collapsed_dragged = True

        if self.active_mode == self.RUBBERBAND_MODE:
            if not self.rubberband_item.scene():
                self.addItem(self.rubberband_item)
                self.rubberband_item.bring_to_front()
            self.rubberband_item.fit(self.event_start, event.scenePos())
            with self.batch_update():
                self.setSelectionArea(
                    self.rubberband_item.shape(),
                    Qt.ItemSelectionOperation.ReplaceSelection,
                    Qt.ItemSelectionMode.IntersectsItemShape,
                    view.transform(),
                )
                sids_to_expand = set()
                for it in list(super().selectedItems()):
                    if not hasattr(it, 'save_id'):
                        continue
                    if not it.isVisible():
                        it.setSelected(False)
                    else:
                        sid = getattr(it, 'stack_id', None)
                        if sid and self.stack_manager.active_spread_stack_id != sid:
                            sids_to_expand.add(sid)
                for sid in sids_to_expand:
                    for m in self.stack_manager.members_of(sid):
                        if m.isVisible() and not m.isSelected():
                            m.setSelected(True)
            view.reset_previous_transform()
            event.accept()
            return
        super().mouseMoveEvent(event)
        if self.active_mode == self.MOVE_MODE and moved_px >= 1:
            self.stack_manager.sync_selected_stack_labels()

    def mouseReleaseEvent(self, event):
        view = self.views()[0]
        # --- Spread Session Release ---
        if self._spread_press_item is not None:
            sp_item = self._spread_press_item
            orig_p = self._spread_press_orig_pos
            was_dragged = self._spread_dragged
            self._spread_press_item = None
            self._spread_dragged = False
            self.active_mode = None
            super().mouseReleaseEvent(event)

            if not was_dragged:
                sp_item.setPos(orig_p)
                self.stack_manager._dragging_item = None
                view.open_detail_stage(sp_item)
            else:
                self.stack_manager.finish_spread_drag(sp_item, orig_p)
            return

        # Single-click on a Collapsed Stack keeps it selected for easy Move/Resize;
        # Double-click (in mouseDoubleClickEvent) spreads the stack.
        self._pressed_collapsed_sid = None
        self._collapsed_dragged = False

        if self.active_mode == self.RUBBERBAND_MODE:
            self.end_rubberband_mode()

        if (self.active_mode == self.MOVE_MODE
                and self.has_selection()
                and self.multi_select_item.active_mode is None
                and self.selectedItems()[0].active_mode is None):
            delta = event.scenePos() - self.event_start
            if not delta.isNull():
                sel_user = self.selectedItems(user_only=True)
                # Gather hidden deep members of any moved collapsed stacks
                hidden_comp = []
                seen_sids = {
                    it.stack_id for it in sel_user
                    if getattr(it, 'stack_id', None)
                    and self.stack_manager.active_spread_stack_id != it.stack_id
                }
                sel_ids = {id(it) for it in sel_user}
                for sid in seen_sids:
                    for m in self.stack_manager.members_of(sid):
                        if id(m) not in sel_ids and not m.isVisible():
                            hidden_comp.append(m)
                self.undo_stack.push(
                    commands.MoveItemsBy(
                        sel_user,
                        delta,
                        ignore_first_redo=True,
                        hidden_companions=hidden_comp,
                    ))
        self.active_mode = None
        super().mouseReleaseEvent(event)

    def selectedItems(self, user_only=False):
        items = super().selectedItems()
        if user_only:
            return [i for i in items if hasattr(i, 'save_id')]
        return items

    def items_by_type(self, itype):
        return (i for i in self.items() if getattr(i, 'TYPE', None) == itype)

    def items_for_save(self):
        return (
            i for i in self.items(order=Qt.SortOrder.AscendingOrder)
            if hasattr(i, 'save_id')
        )

    def clear_save_ids(self):
        for item in self.items_for_save():
            item.save_id = None

    def on_view_scale_change(self):
        """Only update handle geometry on the 1 active selection box (O(1)) and stack labels (O(G))."""
        if self.multi_select_item.scene():
            self.multi_select_item.on_view_scale_change()
        elif self.has_single_selection():
            for item in super().selectedItems():
                if hasattr(item, 'save_id'):
                    item.on_view_scale_change()
                    break
        if hasattr(self, 'stack_manager') and hasattr(self.stack_manager, 'sync_all_stack_labels'):
            self.stack_manager.sync_all_stack_labels()

    def itemsBoundingRect(self, selection_only=False, items=None):
        """Cached O(1) scene/selection bounding box using C++ QTransform.mapRect."""
        if items is not None:
            if not items:
                return QtCore.QRectF(0, 0, 0, 0)
            if len(items) == 1:
                return self._item_scene_rect_fast(items[0])
            base = items
        elif selection_only:
            if self._cached_sel_bounds is not None:
                return QtCore.QRectF(self._cached_sel_bounds)
            base = [i for i in super().selectedItems() if hasattr(i, 'save_id') and i.isVisible()]
        else:
            if self._cached_all_bounds is not None:
                return QtCore.QRectF(self._cached_all_bounds)
            base = [i for i in self.items() if hasattr(i, 'save_id') and i.isVisible()]

        if not base:
            empty = QtCore.QRectF(0, 0, 0, 0)
            if items is None:
                if selection_only:
                    self._cached_sel_bounds = empty
                else:
                    self._cached_all_bounds = empty
            return QtCore.QRectF(empty)

        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for item in base:
            r = item.sceneTransform().mapRect(item.bounding_rect_unselected())
            x1 = r.left()
            y1 = r.top()
            x2 = r.right()
            y2 = r.bottom()
            if x1 < min_x:
                min_x = x1
            if y1 < min_y:
                min_y = y1
            if x2 > max_x:
                max_x = x2
            if y2 > max_y:
                max_y = y2

        result = QtCore.QRectF(
            QtCore.QPointF(min_x, min_y),
            QtCore.QPointF(max_x, max_y),
        )
        if items is None:
            if selection_only:
                self._cached_sel_bounds = result
            else:
                self._cached_all_bounds = result
        return QtCore.QRectF(result)

    def get_selection_center(self):
        rect = self.itemsBoundingRect(selection_only=True)
        return (rect.topLeft() + rect.bottomRight()) / 2

    def on_selection_change(self):
        if self._clear_ongoing:
            return
        self._cached_sel_bounds = None
        if self._batch_depth > 0:
            self._batch_dirty_selection = True
            return

        # Keep visible members of any collapsed stack selected together as one unit
        if not self._expanding_stack_sel and self.stack_manager.active_spread_stack_id is None:
            raw_sel = [i for i in super().selectedItems() if hasattr(i, 'save_id')]
            invis_sel = [i for i in raw_sel if not i.isVisible()]
            vis_sel = [i for i in raw_sel if i.isVisible()]
            sids = {i.stack_id for i in vis_sel if getattr(i, 'stack_id', None)}
            if invis_sel or sids:
                self._expanding_stack_sel = True
                try:
                    for it in invis_sel:
                        it.setSelected(False)
                    for sid in sids:
                        for m in self.stack_manager.members_of(sid):
                            if m.isVisible() and not m.isSelected():
                                m.setSelected(True)
                    self._cached_sel_bounds = None
                finally:
                    self._expanding_stack_sel = False

        multi = self.has_multi_selection()
        if multi:
            self.multi_select_item.fit_selection_area(
                self.itemsBoundingRect(selection_only=True))
            if not self.multi_select_item.scene():
                super().addItem(self.multi_select_item)
                self.multi_select_item.bring_to_front()
        elif self.multi_select_item.scene():
            super().removeItem(self.multi_select_item)

    def on_change(self, region):
        if self._clear_ongoing:
            return
        self.invalidate_bounds_cache()
        if self._batch_depth > 0:
            self._batch_dirty_change = True
            return

        if (self.multi_select_item.scene()
                and self.multi_select_item.active_mode is None):
            self.multi_select_item.fit_selection_area(
                self.itemsBoundingRect(selection_only=True))

    def add_item_later(self, itemdata, selected=False):
        self.items_to_add.put((itemdata, selected))

    def take_pending_inserted_items(self) -> list:
        items = self._pending_insert_items
        self._pending_insert_items = []
        return items

    def add_queued_items(self):
        """Drain queued items inside a single O(N) batch update on the GUI thread."""
        if self.items_to_add.empty():
            return

        drained = []
        while True:
            try:
                drained.append(self.items_to_add.get_nowait())
            except Empty:
                break

        if not drained:
            return

        # Keep deterministic file order within each drained batch
        drained.sort(key=lambda pair: pair[0].get('order_idx', 0))

        with self.batch_update():
            for data, selected in drained:
                data = dict(data)
                data.pop('order_idx', None)
                center_pos = data.pop('center_pos', None)
                typ = data.pop('type')
                cls = item_registry.get(typ)
                if not cls:
                    logger.warning(f'Encountered item of unknown type: {typ}')
                    cls = BeeErrorItem
                    data['data'] = {'text': f'Item of unknown type: {typ}'}
                item = cls.create_from_data(**data)
                item.update_from_data(**data)
                if center_pos is not None:
                    item.set_pos_center(center_pos)
                super().addItem(item)
                item.setZValue(item.zValue())
                if selected:
                    item.setSelected(True)
                    item.bring_to_front()
                    self._pending_insert_items.append(item)
