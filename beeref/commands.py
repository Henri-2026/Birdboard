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

from contextlib import nullcontext
from PyQt6 import QtCore, QtGui, QtWidgets


def _scene_batch(items_or_scene):
    scene = None
    if hasattr(items_or_scene, 'batch_update'):
        scene = items_or_scene
    elif items_or_scene:
        first = next(iter(items_or_scene), None)
        if first is not None and callable(getattr(first, 'scene', None)):
            scene = first.scene()
    return scene.batch_update() if scene is not None else nullcontext()


def _sync_stack_labels_for_items(items):
    if not items:
        return
    first = next(iter(items), None)
    if first is None or not callable(getattr(first, 'scene', None)):
        return
    sc = first.scene()
    if sc is None or not hasattr(sc, 'stack_manager'):
        return
    sids = {
        getattr(it, 'stack_id', None) for it in items
        if getattr(it, 'stack_id', None)
    }
    for sid in sids:
        sc.stack_manager.sync_stack_label(sid)


class InsertItems(QtGui.QUndoCommand):

    def __init__(self, scene, items, position=None, ignore_first_redo=False):
        super().__init__('Insert items')
        self.scene = scene
        self.items = items
        self.position = position
        self.ignore_first_redo = ignore_first_redo

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            return

        with self.scene.batch_update():
            self.scene.deselect_all_items()
            if self.position and self.items:
                self.old_positions = []
                rect = self.scene.itemsBoundingRect(items=self.items)
                offset = self.position - rect.center()
                for item in self.items:
                    self.old_positions.append(item.pos())
                    item.setPos(item.pos() + offset)
            for item in self.items:
                self.scene.addItem(item)
                item.setSelected(True)
                item.bring_to_front()

    def undo(self):
        with self.scene.batch_update():
            self.scene.deselect_all_items()
            for item in self.items:
                self.scene.removeItem(item)
            if self.position and hasattr(self, 'old_positions'):
                for item, pos in zip(self.items, self.old_positions):
                    item.setPos(pos)


class DeleteItems(QtGui.QUndoCommand):
    def __init__(self, scene, items):
        super().__init__('Delete items')
        self.scene = scene
        self.items = list(items)

    def redo(self):
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.cancel_flights_for(self.items)
        with self.scene.batch_update():
            for item in self.items:
                self.scene.removeItem(item)
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.on_items_added_or_removed()
            if self.scene.stack_manager.active_spread_stack_id:
                self.scene.stack_manager.refresh_active_spread_layout()

    def undo(self):
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.cancel_flights_for(self.items)
        with self.scene.batch_update():
            self.scene.deselect_all_items()
            for item in self.items:
                self.scene.addItem(item)
            if hasattr(self.scene, 'stack_manager'):
                self.scene.stack_manager.on_items_added_or_removed()
                if self.scene.stack_manager.active_spread_stack_id:
                    self.scene.stack_manager.refresh_active_spread_layout()
            for item in self.items:
                if item.isVisible():
                    item.setSelected(True)
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.sync_all_stack_labels()


class MoveItemsBy(QtGui.QUndoCommand):

    def __init__(self, items, delta, ignore_first_redo=False, hidden_companions=None):
        super().__init__('Move items')
        self.items = [i for i in items if hasattr(i, 'save_id')]
        self.hidden_companions = list(hidden_companions or [])
        self.delta = delta
        self.ignore_first_redo = ignore_first_redo

    def _shift_stack_centers(self):
        all_it = self.items + self.hidden_companions
        if not all_it:
            return
        sc = all_it[0].scene()
        if sc is None or not hasattr(sc, 'stack_manager'):
            return
        seen = set()
        for it in all_it:
            sid = getattr(it, 'stack_id', None)
            if sid and sid not in seen and sc.stack_manager.active_spread_stack_id != sid:
                seen.add(sid)
                c = sc.stack_manager.get_stack_center(sid)
                sc.stack_manager.set_stack_center(sid, c)
                sc.stack_manager.sync_stack_label(sid)

    def redo(self):
        dx, dy = self.delta.x(), self.delta.y()
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            # Qt already moved visible selected items; move hidden stack companions too!
            if self.hidden_companions:
                with _scene_batch(self.hidden_companions):
                    for h in self.hidden_companions:
                        h.moveBy(dx, dy)
            self._shift_stack_centers()
            return
        with _scene_batch(self.items):
            for item in self.items + self.hidden_companions:
                item.moveBy(dx, dy)
        self._shift_stack_centers()

    def undo(self):
        dx, dy = -self.delta.x(), -self.delta.y()
        with _scene_batch(self.items):
            for item in self.items + self.hidden_companions:
                item.moveBy(dx, dy)
        self._shift_stack_centers()


class ScaleItemsBy(QtGui.QUndoCommand):
    """Scale items by a given factor around the given anchor."""

    def __init__(self, items, factor, anchor, ignore_first_redo=False):
        super().__init__('Scale items')
        self.ignore_first_redo = ignore_first_redo
        self.items = [i for i in items if hasattr(i, 'save_id')]
        self.factor = max(0.04, float(factor))
        self.anchor = anchor

    def _sync_stack_scale(self, mult: float):
        if not self.items:
            return
        sc = self.items[0].scene()
        sids = set()
        for item in self.items:
            if getattr(item, 'stack_saved_scale', None) is not None:
                item.stack_saved_scale = max(1e-4, item.stack_saved_scale * mult)
            if getattr(item, 'stack_id', None):
                sids.add(item.stack_id)
        if sc and hasattr(sc, 'stack_manager'):
            for sid in sids:
                if sc.stack_manager.active_spread_stack_id != sid:
                    members = sc.stack_manager.members_of(sid)
                    if members:
                        sc.stack_manager.set_stack_center(sid, members[0].center_scene_coords)
                        members[0].prepareGeometryChange()
                        members[0].update()
                    sc.stack_manager.sync_stack_label(sid)

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            self._sync_stack_scale(self.factor)
            return
        with _scene_batch(self.items):
            for item in self.items:
                item.setScale(item.scale() * self.factor,
                              item.mapFromScene(self.anchor))
        self._sync_stack_scale(self.factor)

    def undo(self):
        with _scene_batch(self.items):
            for item in self.items:
                item.setScale(item.scale() / self.factor,
                              item.mapFromScene(self.anchor))
        self._sync_stack_scale(1.0 / self.factor)


class RotateItemsBy(QtGui.QUndoCommand):
    """Rotate items by a given delta around the given anchor."""

    def __init__(self, items, delta, anchor, ignore_first_redo=False):
        super().__init__('Rotate items')
        self.ignore_first_redo = ignore_first_redo
        self.items = [i for i in items if hasattr(i, 'save_id')]
        self.delta = delta
        self.anchor = anchor

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            _sync_stack_labels_for_items(self.items)
            return
        with _scene_batch(self.items):
            for item in self.items:
                item.setRotation(
                    item.rotation() + self.delta * item.flip(),
                    item.mapFromScene(self.anchor))
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        with _scene_batch(self.items):
            for item in self.items:
                item.setRotation(item.rotation() - self.delta * item.flip(),
                                 item.mapFromScene(self.anchor))
        _sync_stack_labels_for_items(self.items)


class NormalizeItems(QtGui.QUndoCommand):

    def __init__(self, items, scale_factors):
        super().__init__('Normalize items')
        self.items = list(items)
        self.scale_factors = list(scale_factors)

    def redo(self):
        self.old_scale_factors = []
        with _scene_batch(self.items):
            for item, factor in zip(self.items, self.scale_factors):
                self.old_scale_factors.append(item.scale())
                item.setScale(item.scale() * factor, item.center)
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        with _scene_batch(self.items):
            for item, factor in zip(self.items, self.old_scale_factors):
                item.setScale(factor, item.center)
        _sync_stack_labels_for_items(self.items)


class FlipItems(QtGui.QUndoCommand):

    def __init__(self, items, anchor, vertical):
        super().__init__('Flip items')
        self.items = [i for i in items if hasattr(i, 'save_id')]
        self.anchor = anchor
        self.vertical = vertical

    def redo(self):
        with _scene_batch(self.items):
            for item in self.items:
                item.do_flip(self.vertical, item.mapFromScene(self.anchor))
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        self.redo()


class ResetScale(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Scale')
        self.items = list(items)

    def redo(self):
        self.old_scale_factors = []
        with _scene_batch(self.items):
            for item in self.items:
                self.old_scale_factors.append(item.scale())
                item.setScale(1, anchor=item.center)
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        with _scene_batch(self.items):
            for item, scale_factor in zip(self.items, self.old_scale_factors):
                item.setScale(scale_factor, anchor=item.center)
        _sync_stack_labels_for_items(self.items)


class ResetRotation(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Rotation')
        self.items = list(items)

    def redo(self):
        self.old_rotations = []
        with _scene_batch(self.items):
            for item in self.items:
                self.old_rotations.append(item.rotation())
                item.setRotation(0, anchor=item.center)
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        with _scene_batch(self.items):
            for item, rotation in zip(self.items, self.old_rotations):
                item.setRotation(rotation, anchor=item.center)
        _sync_stack_labels_for_items(self.items)


class ResetFlip(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Flip')
        self.items = list(items)

    def redo(self):
        self.old_flips = []
        with _scene_batch(self.items):
            for item in self.items:
                self.old_flips.append(item.flip())
                if item.flip() == -1:
                    item.do_flip(anchor=item.center)
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        with _scene_batch(self.items):
            for item, flip in zip(self.items, self.old_flips):
                if flip == -1:
                    item.do_flip(anchor=item.center)
        _sync_stack_labels_for_items(self.items)


class ResetCrop(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset Crop')
        self.items = [item for item in items if item.is_image]

    def redo(self):
        self.old_crops = []
        with _scene_batch(self.items):
            for item in self.items:
                self.old_crops.append(item.crop)
                item.reset_crop()
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        with _scene_batch(self.items):
            for item, crop in zip(self.items, self.old_crops):
                item.crop = crop
        _sync_stack_labels_for_items(self.items)


class ResetTransforms(QtGui.QUndoCommand):

    def __init__(self, items):
        super().__init__('Reset All Transformations')
        self.items = list(items)

    def redo(self):
        self.old_values = []
        with _scene_batch(self.items):
            for item in self.items:
                values = {
                    'scale': item.scale(),
                    'rotation': item.rotation(),
                    'flip': item.flip(),
                }
                if item.is_image:
                    values['crop'] = item.crop
                    item.reset_crop()
                self.old_values.append(values)

                item.setScale(1, anchor=item.center)
                item.setRotation(0, anchor=item.center)
                if item.flip() == -1:
                    item.do_flip(anchor=item.center)
        _sync_stack_labels_for_items(self.items)

    def undo(self):
        with _scene_batch(self.items):
            for item, old in zip(self.items, self.old_values):
                item.setScale(old['scale'], anchor=item.center)
                item.setRotation(old['rotation'], anchor=item.center)
                if old['flip'] == -1:
                    item.do_flip(anchor=item.center)
                if item.is_image:
                    item.crop = old['crop']
        _sync_stack_labels_for_items(self.items)


class ArrangeItems(QtGui.QUndoCommand):

    def __init__(self, scene, items, positions):
        super().__init__('Arrange items')
        self.scene = scene
        self.items = list(items)
        self.positions = list(positions)

    def _move_collapsed_companions(self, item, delta: QtCore.QPointF):
        sid = getattr(item, 'stack_id', None)
        if not sid or not hasattr(self.scene, 'stack_manager'):
            return
        if self.scene.stack_manager.active_spread_stack_id == sid:
            return
        dx, dy = delta.x(), delta.y()
        members = self.scene.stack_manager.members_of(sid)
        self.scene.stack_manager.cancel_flights_for(members)
        for m in members:
            if m is not item:
                m.moveBy(dx, dy)
        self.scene.stack_manager.set_stack_center(sid, item.center_scene_coords)
        self.scene.stack_manager.sync_stack_label(sid)

    def redo(self):
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.cancel_flights_for(self.items)
        self.old_positions = []
        with self.scene.batch_update():
            for item, pos in zip(self.items, self.positions):
                old_p = QtCore.QPointF(item.pos())
                self.old_positions.append(old_p)
                orig_topleft = item.mapToScene(QtCore.QPointF(0, 0))
                unit_local = (
                    item._collapsed_pile_local_rect()
                    if (hasattr(item, '_is_collapsed_stack_cover') and item._is_collapsed_stack_cover())
                    else item.bounding_rect_unselected()
                )
                rect_topleft = item.sceneTransform().mapRect(unit_local).topLeft()
                new_p = pos + orig_topleft - rect_topleft
                item.setPos(new_p)
                self._move_collapsed_companions(item, new_p - old_p)

    def undo(self):
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.cancel_flights_for(self.items)
        with self.scene.batch_update():
            for item, pos in zip(self.items, self.old_positions):
                cur_p = QtCore.QPointF(item.pos())
                item.setPos(pos)
                self._move_collapsed_companions(item, pos - cur_p)


class CropItem(QtGui.QUndoCommand):
    def __init__(self, item, crop):
        super().__init__('Crop item')
        self.item = item
        self.crop = crop

    def redo(self):
        self.old_crop = self.item.crop
        self.item.crop = self.crop
        _sync_stack_labels_for_items([self.item])

    def undo(self):
        self.item.crop = self.old_crop
        _sync_stack_labels_for_items([self.item])


class ChangeText(QtGui.QUndoCommand):

    def __init__(self, item, new_text, old_text):
        super().__init__('Change text')
        self.item = item
        self.new_text = new_text
        self.old_text = old_text

    def redo(self):
        self.item.setPlainText(self.new_text)

    def undo(self):
        self.item.setPlainText(self.old_text)


class ChangeOpacity(QtGui.QUndoCommand):
    """Change opacity on images."""

    def __init__(self, items, opacity, ignore_first_redo=False):
        super().__init__('Change Opacity')
        self.ignore_first_redo = ignore_first_redo
        self.items = [item for item in items if item.is_image]
        self.opacity = opacity
        self.old_opacities = [item.opacity() for item in self.items]

    def redo(self):
        if self.ignore_first_redo:
            self.ignore_first_redo = False
            return
        with _scene_batch(self.items):
            for item in self.items:
                item.setOpacity(self.opacity)

    def undo(self):
        with _scene_batch(self.items):
            for item, opacity in zip(self.items, self.old_opacities):
                item.setOpacity(opacity)


class ToggleGrayscale(QtGui.QUndoCommand):
    """Toggle grayscale mode on images."""

    def __init__(self, items, grayscale):
        super().__init__('Toggle Grayscale')
        self.items = [item for item in items if item.is_image]
        self.grayscale = grayscale
        self.old_grayscales = [item.grayscale for item in self.items]

    def redo(self):
        with _scene_batch(self.items):
            for item in self.items:
                item.grayscale = self.grayscale

    def undo(self):
        with _scene_batch(self.items):
            for item, grayscale in zip(self.items, self.old_grayscales):
                item.grayscale = grayscale


class CreateStackCommand(QtGui.QUndoCommand):
    """Collapse >= 2 items into a Stack Group with Cover priority."""

    def __init__(self, scene, items, stack_id: str, center: QtCore.QPointF):
        super().__init__('Create Stack Group')
        self.scene = scene
        self.stack_id = stack_id
        self.center = QtCore.QPointF(center)
        # Highest zValue item (or first selected image) becomes initial Cover
        img_items = [it for it in items if getattr(it, 'is_image', False)]
        # Sort descending by zValue so visually topmost image becomes default cover
        img_items.sort(key=lambda it: it.zValue(), reverse=True)
        self.items = img_items
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.cancel_flights_for(self.items)
        self._snapshots = [self._capture(it) for it in self.items]

    @staticmethod
    def _capture(it) -> dict:
        return {
            'pos': QtCore.QPointF(it.pos()),
            'scale': it.scale(),
            'rot': it.rotation(),
            'z': it.zValue(),
            'vis': it.isVisible(),
            'stack_id': getattr(it, 'stack_id', None),
            'is_cover': getattr(it, 'is_stack_cover', False),
            'order': getattr(it, 'stack_order', 0),
            'name': getattr(it, 'stack_name', ''),
            'saved_scale': getattr(it, 'stack_saved_scale', None),
            'saved_rot': getattr(it, 'stack_saved_rot', None),
        }

    @staticmethod
    def _restore(it, snap: dict):
        it.prepareGeometryChange()
        it.stack_id = snap['stack_id']
        it.is_stack_cover = snap['is_cover']
        it.stack_order = snap['order']
        it.stack_name = snap['name']
        it.stack_saved_scale = snap['saved_scale']
        it.stack_saved_rot = snap['saved_rot']
        QtWidgets.QGraphicsItem.setRotation(it, snap['rot'])
        QtWidgets.QGraphicsItem.setScale(it, snap['scale'])
        it.setPos(snap['pos'])
        it.setZValue(snap['z'])
        it.setVisible(snap['vis'])
        it.update()

    def redo(self):
        if len(self.items) < 2:
            return
        self.scene.stack_manager.cancel_flights_for(self.items)
        existing_name = ''
        for it in self.items:
            if getattr(it, 'stack_name', ''):
                existing_name = it.stack_name
                break

        for idx, it in enumerate(self.items):
            if getattr(it, 'stack_saved_scale', None) is None:
                it.stack_saved_scale = it.scale()
            if getattr(it, 'stack_saved_rot', None) is None:
                it.stack_saved_rot = it.rotation()
            it.stack_id = self.stack_id
            it.is_stack_cover = (idx == 0)
            it.stack_order = idx
            it.stack_name = existing_name

        self.scene.stack_manager.apply_collapsed_pile(
            self.stack_id, center=self.center, animate=True, pop=True)
        with self.scene.batch_update():
            self.scene.clearSelection()
            for it in self.items:
                if it.isVisible():
                    it.setSelected(True)

    def undo(self):
        if self.scene.stack_manager.active_spread_stack_id == self.stack_id:
            self.scene.stack_manager.collapse_spread_stack(animate=False)
        self.scene.stack_manager.cancel_flights_for(self.items)
        with self.scene.batch_update():
            self.scene.clearSelection()
            for it, snap in zip(self.items, self._snapshots):
                self._restore(it, snap)
                if it.isVisible():
                    it.setSelected(True)
        self.scene.stack_manager.invalidate_stack_cache()
        self.scene.stack_manager.sync_stack_label(self.stack_id)
        restored_sids = {
            snap['stack_id'] for snap in self._snapshots if snap['stack_id']
        }
        for rsid in restored_sids:
            self.scene.stack_manager.sync_stack_label(rsid)


class UnstackCommand(QtGui.QUndoCommand):
    """Dissolve a Stack Group back into individual spread-out images."""

    def __init__(self, scene, stack_id: str):
        super().__init__('Unstack Group')
        self.scene = scene
        self.stack_id = stack_id
        self.members = self.scene.stack_manager.members_of(stack_id)
        if hasattr(self.scene, 'stack_manager'):
            self.scene.stack_manager.cancel_flights_for(self.members)
        self.center = self.scene.stack_manager.get_stack_center(stack_id)
        self._snapshots = [CreateStackCommand._capture(it) for it in self.members]

    def redo(self):
        if self.scene.stack_manager.active_spread_stack_id == self.stack_id:
            self.scene.stack_manager.collapse_spread_stack(animate=False)
        self.scene.stack_manager.cancel_flights_for(self.members)

        targets, _ = self.scene.stack_manager.compute_spread_grid(
            self.members, self.center)
        with self.scene.batch_update():
            self.scene.clearSelection()
            for it in self.members:
                sc = it.stack_saved_scale if it.stack_saved_scale is not None else it.scale()
                it.stack_id = None
                it.is_stack_cover = False
                it.stack_order = 0
                it.stack_name = ''
                it.stack_saved_scale = None
                it.stack_saved_rot = None
                it.setVisible(True)
                if it in targets:
                    tpos, tsc = targets[it]
                    self.scene.stack_manager._start_flight(
                        it, to_pos=tpos, to_scale=tsc, to_rot=0.0, mode='spring')
                else:
                    QtWidgets.QGraphicsItem.setRotation(it, 0.0)
                    QtWidgets.QGraphicsItem.setScale(it, sc)
                it.setSelected(True)
                it.update()
        self.scene.stack_manager.invalidate_stack_cache(self.stack_id)
        self.scene.stack_manager.sync_stack_label(self.stack_id)

    def undo(self):
        self.scene.stack_manager.cancel_flights_for(self.members)
        with self.scene.batch_update():
            self.scene.clearSelection()
            for it, snap in zip(self.members, self._snapshots):
                CreateStackCommand._restore(it, snap)
        self.scene.stack_manager.set_stack_center(self.stack_id, self.center)
        self.scene.stack_manager.invalidate_stack_cache(self.stack_id)
        self.scene.stack_manager.apply_collapsed_pile(
            self.stack_id, center=self.center, animate=False, pop=False)
        with self.scene.batch_update():
            for it in self.members:
                if it.isVisible():
                    it.setSelected(True)
        self.scene.stack_manager.sync_stack_label(self.stack_id)


class SetStackCoverCommand(QtGui.QUndoCommand):
    """Promote chosen item to Group Cover (`is_stack_cover = True`), pushing it to #0."""

    def __init__(self, scene, stack_id: str, new_cover_item):
        super().__init__('Set Group Cover')
        self.scene = scene
        self.stack_id = stack_id
        self.new_cover = new_cover_item
        members = self.scene.stack_manager.members_of(stack_id)
        self.old_cover = next(
            (it for it in members if it.is_stack_cover),
            members[0] if members else new_cover_item,
        )

    def _apply_cover(self, chosen):
        sm = self.scene.stack_manager
        members = sm.members_of(self.stack_id)
        sm.cancel_flights_for(members)
        for it in members:
            it.is_stack_cover = (it is chosen)
            it.update()

        if sm.active_spread_stack_id == self.stack_id:
            # Update z-order and reflow Spread Grid so Cover sits first!
            sm.refresh_active_spread_layout()
        else:
            sm.apply_collapsed_pile(self.stack_id, animate=True, pop=True)

    def redo(self):
        self._apply_cover(self.new_cover)

    def undo(self):
        self._apply_cover(self.old_cover)


class RenameStackCommand(QtGui.QUndoCommand):
    """Set or update the floating Group Name of a Stack."""

    def __init__(self, scene, stack_id: str, old_name: str, new_name: str):
        super().__init__('Rename Stack Group')
        self.scene = scene
        self.stack_id = stack_id
        self.old_name = old_name
        self.new_name = new_name

    def redo(self):
        self.scene.stack_manager.set_stack_name(self.stack_id, self.new_name)

    def undo(self):
        self.scene.stack_manager.set_stack_name(self.stack_id, self.old_name)


class PullOutFromStackCommand(QtGui.QUndoCommand):
    """Detach 1 item dragged outside a Spread Stack's keep_zone."""

    def __init__(self, scene, stack_id: str, item, final_pos: QtCore.QPointF):
        super().__init__('Pull Item Out of Stack')
        self.scene = scene
        self.stack_id = stack_id
        self.item = item
        self.final_pos = QtCore.QPointF(final_pos)
        self._item_snap = CreateStackCommand._capture(item)
        members = self.scene.stack_manager.members_of(stack_id)
        self._others = [m for m in members if m is not item]
        self._other_snaps = [CreateStackCommand._capture(m) for m in self._others]

    def redo(self):
        sm = self.scene.stack_manager
        sm.cancel_flights_for([self.item] + self._others)
        was_cover = bool(self.item.is_stack_cover)

        # Detach pulled item cleanly
        sc = self.item.stack_saved_scale if self.item.stack_saved_scale is not None else self.item.scale()
        self.item.stack_id = None
        self.item.is_stack_cover = False
        self.item.stack_order = 0
        self.item.stack_name = ''
        self.item.stack_saved_scale = None
        self.item.stack_saved_rot = None
        QtWidgets.QGraphicsItem.setRotation(self.item, 0.0)
        QtWidgets.QGraphicsItem.setScale(self.item, sc)
        self.item.setPos(self.final_pos)
        self.item.setVisible(True)
        self.item.update()

        if len(self._others) >= 2:
            if was_cover:
                self._others[0].is_stack_cover = True
                self._others[0].update()
            if sm.active_spread_stack_id == self.stack_id:
                sm.refresh_active_spread_layout()
        elif len(self._others) == 1:
            # Dissolve 1-remaining-item stack automatically
            last = self._others[0]
            last_sc = last.stack_saved_scale if last.stack_saved_scale is not None else last.scale()
            last.stack_id = None
            last.is_stack_cover = False
            last.stack_order = 0
            last.stack_name = ''
            last.stack_saved_scale = None
            last.stack_saved_rot = None
            QtWidgets.QGraphicsItem.setRotation(last, 0.0)
            QtWidgets.QGraphicsItem.setScale(last, last_sc)
            last.setVisible(True)
            last.update()
            if sm.active_spread_stack_id == self.stack_id:
                sm.collapse_spread_stack(animate=True)
        sm.invalidate_stack_cache(self.stack_id)
        sm.sync_stack_label(self.stack_id)

    def undo(self):
        sm = self.scene.stack_manager
        sm.cancel_flights_for([self.item] + self._others)
        with self.scene.batch_update():
            CreateStackCommand._restore(self.item, self._item_snap)
            for m, snap in zip(self._others, self._other_snaps):
                CreateStackCommand._restore(m, snap)
        sm.invalidate_stack_cache(self.stack_id)
        if sm.active_spread_stack_id == self.stack_id:
            sm.refresh_active_spread_layout()
        else:
            sm.apply_collapsed_pile(self.stack_id, animate=True)
            sm.sync_stack_label(self.stack_id)


class EditItemNoteCommand(QtGui.QUndoCommand):

    def __init__(self, item, old_note: str, new_note: str):
        super().__init__('Edit Note')
        self.item = item
        self.old_note = old_note
        self.new_note = new_note

    def redo(self):
        self.item.note = self.new_note

    def undo(self):
        self.item.note = self.old_note


class RenameItemFileCommand(QtGui.QUndoCommand):

    def __init__(self, item, old_title: str, new_title: str):
        super().__init__('Rename Item File')
        self.item = item
        self.old_title = old_title
        self.new_title = new_title

    def redo(self):
        self.item.custom_title = self.new_title

    def undo(self):
        self.item.custom_title = self.old_title
