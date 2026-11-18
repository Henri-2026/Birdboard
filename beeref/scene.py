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

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtCore import Qt

import rpack

from beeref import commands
from beeref.config import BeeSettings
from beeref.items import item_registry, BeeErrorItem, sort_by_filename
from beeref.lod_cache import LODCacheManager
from beeref.selection import MultiSelectItem, RubberbandItem


logger = logging.getLogger(__name__)


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
        LODCacheManager.instance().clear_all()
        super().clear()
        self.internal_clipboard = []
        self._pending_insert_items = []
        self.rubberband_item = RubberbandItem()
        self.multi_select_item = MultiSelectItem()
        self.invalidate_bounds_cache()
        self._clear_ongoing = False

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

    def arrange(self, vertical=False):
        """Arrange items in a line (horizontally or vertically)."""
        self.cancel_active_modes()
        items = sort_by_filename(self.selectedItems(user_only=True))
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

    def arrange_optimal(self):
        self.cancel_active_modes()
        items = self.selectedItems(user_only=True)
        if len(items) < 2:
            return

        gap = self.settings.valueOrDefault('Items/arrange_gap')
        sizes = []
        for item in items:
            rect = self._item_scene_rect_fast(item)
            sizes.append((
                max(1, round(rect.width() + gap)),
                max(1, round(rect.height() + gap)),
            ))

        if len(items) <= 300:
            min_area = sum(s[0] * s[1] for s in sizes)
            max_single_w = max(s[0] for s in sizes)
            max_single_h = max(s[1] for s in sizes)
            width = max(max_single_w, max_single_h, math.ceil(math.sqrt(min_area) * 1.06))

            positions = None
            while not positions:
                try:
                    positions = rpack.pack(
                        sizes, max_width=width, max_height=width)
                except rpack.PackingImpossibleError:
                    width = math.ceil(width * 1.2)
            bounds = rpack.bbox_size(sizes, positions)
        else:
            # Fast O(N log K) masonry packing for 300 - 10,000+ images
            items = sort_by_filename(items)
            sizes = []
            for item in items:
                rect = self._item_scene_rect_fast(item)
                sizes.append((
                    max(1, round(rect.width() + gap)),
                    max(1, round(rect.height() + gap)),
                ))
            positions = _pack_large_masonry(sizes)
            max_x = max(p[0] + s[0] for p, s in zip(positions, sizes))
            max_y = max(p[1] + s[1] for p, s in zip(positions, sizes))
            bounds = (max_x, max_y)

        center = self.get_selection_center()
        diff = center - QtCore.QPointF(bounds[0] / 2, bounds[1] / 2)
        qpositions = [QtCore.QPointF(p[0], p[1]) + diff for p in positions]

        self.undo_stack.push(commands.ArrangeItems(self, items, qpositions))

    def arrange_square(self):
        self.cancel_active_modes()
        gap = self.settings.valueOrDefault('Items/arrange_gap')
        items = sort_by_filename(self.selectedItems(user_only=True))
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
        item_at_pos = self.itemAt(position, self.views()[0].transform())
        if item_at_pos:
            return item_at_pos.sample_color_at(position)

    def select_all_items(self):
        self.cancel_active_modes()
        with self.batch_update():
            for item in self.items():
                if hasattr(item, 'save_id'):
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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self.event_start = event.scenePos()
            item_at_pos = self.itemAt(
                event.scenePos(), self.views()[0].transform())

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
            if item_at_pos:
                self.active_mode = self.MOVE_MODE
            elif self.items():
                self.active_mode = self.RUBBERBAND_MODE

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.cancel_active_modes()
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if item:
            if not item.isSelected():
                item.setSelected(True)
            if item.is_editable:
                item.enter_edit_mode()
                self.mousePressEvent(event)
            else:
                self.views()[0].fit_rect(
                    self._item_scene_rect_fast(item),
                    toggle_item=item)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_mode == self.RUBBERBAND_MODE:
            if not self.rubberband_item.scene():
                self.addItem(self.rubberband_item)
                self.rubberband_item.bring_to_front()
            self.rubberband_item.fit(self.event_start, event.scenePos())
            with self.batch_update():
                self.setSelectionArea(
                    self.rubberband_item.shape(),
                    Qt.ItemSelectionOperation.ReplaceSelection,
                    Qt.ItemSelectionMode.IntersectsItemBoundingRect,
                    self.views()[0].transform(),
                )
            self.views()[0].reset_previous_transform()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.active_mode == self.RUBBERBAND_MODE:
            self.end_rubberband_mode()
        if (self.active_mode == self.MOVE_MODE
                and self.has_selection()
                and self.multi_select_item.active_mode is None
                and self.selectedItems()[0].active_mode is None):
            delta = event.scenePos() - self.event_start
            if not delta.isNull():
                self.undo_stack.push(
                    commands.MoveItemsBy(self.selectedItems(user_only=True),
                                         delta,
                                         ignore_first_redo=True))
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
        """Only update handle geometry on the 1 active selection box (O(1))."""
        if self.multi_select_item.scene():
            self.multi_select_item.on_view_scale_change()
        elif self.has_single_selection():
            for item in super().selectedItems():
                if hasattr(item, 'save_id'):
                    item.on_view_scale_change()
                    break

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
            base = [i for i in super().selectedItems() if hasattr(i, 'save_id')]
        else:
            if self._cached_all_bounds is not None:
                return QtCore.QRectF(self._cached_all_bounds)
            base = [i for i in self.items() if hasattr(i, 'save_id')]

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
