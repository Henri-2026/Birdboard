# This file is part of Birdboard (GPL-3.0-or-later).

"""Full-Viewport Detail Stage View for Birdboard Stack Groups.

Matches the custom Birdboard layout:
  * Top-left: `<-` Back pill button returning smoothly to Spread Grid.
  * Left of image:
      1. Circular 28x28 Group Cover Radio-Checkbox (#FFDA12 when active).
      2. Small inline Group Name input (`Tên nhóm...`) right beneath checkbox
         (synced to `stack_name`, rendered floating below collapsed Group on Board).
      3. Column of 5 dominant color swatches (28x28, sorted brightest -> darkest,
         click to copy HEX).
  * Center: Crisp full-resolution artwork with Spring open (230/28) & close (320/34).
  * Right of image:
      1. `KÍCH THƯỚC` (W × H)
      2. `TÊN TỆP` (Double-click smart inline rename preserving `.jpg`/`.png` ext!)
      3. `NGÀY TẠO` (Full Vietnamese date INCLUDING YEAR: `Tạo vào DD tháng MM, YYYY`)
      4. `Viết ghi chú...` multi-line note field directly below `NGÀY TẠO`!
  * Bottom center: Dark Toolbar (`[Adjust (dimmed/disabled), Copy, Export, Delete]`).
"""

import datetime
import os
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from beeref import commands, constants
from beeref.assets import BeeAssets
from beeref.deskboard_motion import (
    SPRING_CLOSE,
    SPRING_OPEN,
    SPRING_POP,
    extract_dominant_palette,
)
from beeref.widgets.contextual_toolbar import (
    ContextualToolbar,
    DeskboardToast,
    ToolbarButtonSpec,
)


class _SmartFilenameWidget(QtWidgets.QWidget):
    """Displays wrapped filename; double-click edits stem while preserving extension."""

    renamed = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)
        self._full_name = ''
        self._stem = ''
        self._ext = ''
        self._editing = False

        self.layout_stack = QtWidgets.QVBoxLayout(self)
        self.layout_stack.setContentsMargins(0, 0, 0, 0)
        self.layout_stack.setSpacing(2)

        self.label = QtWidgets.QLabel(self)
        self.label.setWordWrap(True)
        self.label.setCursor(Qt.CursorShape.IBeamCursor)
        self.label.setToolTip('Nhấp đúp để đổi tên tệp (giữ nguyên đuôi file)')
        self.label.installEventFilter(self)
        self.layout_stack.addWidget(self.label)

        self.edit_wrap = QtWidgets.QWidget(self)
        row = QtWidgets.QHBoxLayout(self.edit_wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)

        self.line_edit = QtWidgets.QLineEdit(self.edit_wrap)
        self.ext_badge = QtWidgets.QLabel(self.edit_wrap)
        row.addWidget(self.line_edit, stretch=1)
        row.addWidget(self.ext_badge)
        self.edit_wrap.hide()
        self.layout_stack.addWidget(self.edit_wrap)

        self.line_edit.returnPressed.connect(self.commit_edit)
        self.line_edit.editingFinished.connect(self.commit_edit)
        self.line_edit.installEventFilter(self)

    def set_filename(self, name: str):
        self._editing = False
        self.edit_wrap.hide()
        self.label.show()
        self._full_name = name or 'Untitled.png'
        stem, ext = os.path.splitext(self._full_name)
        self._stem = stem or 'Untitled'
        self._ext = ext
        # Insert zero-width break hints after '_' or '-' so very long filenames wrap cleanly
        display = self._full_name.replace('_', '_\u200b').replace('-', '-\u200b')
        self.label.setText(display)

    def apply_theme(self, is_dark: bool):
        assets = BeeAssets()
        f_val = assets.font(12, 400)
        f_ext = assets.font(12, 600)
        self.label.setFont(f_val)
        self.line_edit.setFont(f_val)
        self.ext_badge.setFont(f_ext)

        fg_sec = '#9E9FA6' if is_dark else '#6E6F75'
        fg_main = '#EDEDEF' if is_dark else '#1A1A1C'
        edit_bg = '#2A2B2E' if is_dark else '#F2F3F5'
        rim = 'rgba(255,255,255,0.18)' if is_dark else 'rgba(26,26,28,0.18)'

        self.label.setStyleSheet(f'color: {fg_sec}; background: transparent;')
        self.ext_badge.setStyleSheet(f'color: {fg_sec}; padding-left: 2px;')
        self.line_edit.setStyleSheet(
            f'QLineEdit {{ color: {fg_main}; background: {edit_bg}; '
            f'border: 1px solid {rim}; border-radius: 5px; padding: 3px 6px; }}'
        )

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def start_edit(self):
        if self._editing:
            return
        self._editing = True
        self.label.hide()
        self.ext_badge.setText(self._ext)
        self.ext_badge.setVisible(bool(self._ext))
        self.line_edit.setText(self._stem)
        self.edit_wrap.show()
        self.line_edit.setFocus()
        self.line_edit.selectAll()

    def cancel_edit(self):
        if not self._editing:
            return
        self._editing = False
        self.edit_wrap.hide()
        self.label.show()

    def commit_edit(self):
        if not self._editing:
            return
        self._editing = False
        raw = self.line_edit.text().strip()
        # Strip forbidden filename chars and accidental duplicate extension
        for ch in '<>:"/\\|?*':
            raw = raw.replace(ch, '_')
        if self._ext and raw.lower().endswith(self._ext.lower()):
            raw = raw[:-len(self._ext)].strip()

        self.edit_wrap.hide()
        self.label.show()

        if not raw:
            return
        new_full = f'{raw}{self._ext}'
        if new_full != self._full_name:
            self.set_filename(new_full)
            self.renamed.emit(new_full)

    def eventFilter(self, obj, event):
        if obj is self.label and event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton:
                self.start_edit()
                return True
        if obj is self.line_edit and event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_edit()
                return True
        return super().eventFilter(obj, event)


class DetailStageOverlay(QtWidgets.QWidget):
    """Full-screen gallery detail view for inspecting an image in a Stack."""

    closed = QtCore.pyqtSignal()
    delete_requested = QtCore.pyqtSignal(object)

    SWATCH_DIAM = 28.0
    SWATCH_GAP = 10.0
    COVER_DIAM = 28.0

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.item = None
        self._origin_rect = QtCore.QRectF()
        self._target_img_rect = QtCore.QRectF()
        self._current_img_rect = QtCore.QRectF()

        self._anim_mode = 'idle'  # 'open', 'close', 'idle'
        self._anim_t0 = 0.0
        self._backdrop_alpha = 0.0
        self._chrome_alpha = 0.0

        self._cover_pop_t0 = -1.0
        self._cover_scale = 1.0
        self._hovered_cover = False
        self._hovered_back = False
        self._hovered_swatch = -1

        self._display_pixmap = QtGui.QPixmap()
        self._swatches: list[str] = []
        self._initial_note = ''
        self._initial_group_name = ''

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # --- Group Name input right below Cover Tick Circle (left column) ---
        self.group_name_edit = QtWidgets.QLineEdit(self)
        self.group_name_edit.setPlaceholderText('Tên nhóm...')
        self.group_name_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.group_name_edit.setMaxLength(48)
        self.group_name_edit.setToolTip(
            'Đặt tên cho nhóm xếp chồng (hiển thị bên dưới nhóm ngoài bảng chính)')
        self.group_name_edit.returnPressed.connect(self.setFocus)
        self.group_name_edit.editingFinished.connect(self._commit_group_name)

        # --- Right Metadata + Note Panel ---
        self.right_panel = QtWidgets.QWidget(self)
        rp_layout = QtWidgets.QVBoxLayout(self.right_panel)
        rp_layout.setContentsMargins(0, 0, 0, 0)
        rp_layout.setSpacing(4)

        self.lbl_dim_hdr = QtWidgets.QLabel('KÍCH THƯỚC', self.right_panel)
        self.lbl_dim_val = QtWidgets.QLabel('', self.right_panel)
        rp_layout.addWidget(self.lbl_dim_hdr)
        rp_layout.addWidget(self.lbl_dim_val)
        rp_layout.addSpacing(12)

        self.lbl_file_hdr = QtWidgets.QLabel('TÊN TỆP', self.right_panel)
        self.filename_widget = _SmartFilenameWidget(self.right_panel)
        self.filename_widget.renamed.connect(self._on_filename_renamed)
        rp_layout.addWidget(self.lbl_file_hdr)
        rp_layout.addWidget(self.filename_widget)
        rp_layout.addSpacing(12)

        self.lbl_date_hdr = QtWidgets.QLabel('NGÀY TẠO', self.right_panel)
        self.lbl_date_val = QtWidgets.QLabel('', self.right_panel)
        self.lbl_date_val.setWordWrap(True)
        rp_layout.addWidget(self.lbl_date_hdr)
        rp_layout.addWidget(self.lbl_date_val)
        rp_layout.addSpacing(16)

        # Note input right below NGÀY TẠO in the right column!
        self.note_edit = QtWidgets.QPlainTextEdit(self.right_panel)
        self.note_edit.setPlaceholderText('Viết ghi chú...')
        self.note_edit.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.note_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.note_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.note_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.note_edit.document().setDocumentMargin(0.0)
        self.note_edit.setMinimumHeight(96)
        rp_layout.addWidget(self.note_edit, stretch=1)

        # --- Bottom Dark Toolbar (4 buttons; Adjust icon dimmed/disabled) ---
        self.stage_toolbar = ContextualToolbar(self, force_dark_bg=True)
        self.stage_toolbar.action_triggered.connect(self._on_toolbar_action)

        self._anim_timer = QtCore.QTimer(self)
        self._anim_timer.setInterval(8)
        self._anim_timer.timeout.connect(self._on_anim_tick)

        self.hide()

    def open_for_item(self, item, origin_view_rect: QtCore.QRectF):
        self.item = item
        self.resize(self.view.size())
        self._origin_rect = QtCore.QRectF(origin_view_rect)

        # Request full-resolution pixmap for crystal-clear stage inspection
        self._display_pixmap = item.pixmap()
        if self._display_pixmap.isNull():
            self._display_pixmap = item.thumb_pixmap

        if not getattr(item, 'palette_hex', None):
            item.palette_hex = extract_dominant_palette(item.thumb_pixmap, count=5)
        self._swatches = list(item.palette_hex)

        # Populate metadata
        w, h = item._orig_width, item._orig_height
        self.lbl_dim_val.setText(f'{w} × {h}')
        self.filename_widget.set_filename(item.display_filename)
        self.lbl_date_val.setText(self._format_created_date(item))

        self._initial_note = getattr(item, 'note', '') or ''
        self.note_edit.setPlainText(self._initial_note)

        has_stack = bool(getattr(item, 'stack_id', None))
        self.group_name_edit.setVisible(has_stack)
        if has_stack:
            gname = self.view.scene.stack_manager.get_stack_name(item.stack_id)
            self._initial_group_name = gname
            self.group_name_edit.setText(gname)
        else:
            self._initial_group_name = ''
            self.group_name_edit.setText('')

        self.apply_theme()
        self._compute_layout_rects()

        self._current_img_rect = (
            QtCore.QRectF(self._origin_rect)
            if not self._origin_rect.isEmpty()
            else QtCore.QRectF(self._target_img_rect)
        )
        self._backdrop_alpha = 0.0
        self._chrome_alpha = 0.0
        self.right_panel.hide()
        self.group_name_edit.hide()

        self.stage_toolbar.set_buttons([
            ToolbarButtonSpec(
                'adjust', 'sliders', 'Điều chỉnh (Sắp ra mắt)', enabled=False),
            ToolbarButtonSpec(
                'copy', 'duplicate', 'Sao chép hình ảnh', enabled=True),
            ToolbarButtonSpec(
                'export', 'download', 'Xuất hình ảnh', enabled=True),
            ToolbarButtonSpec(
                'delete', 'trash', 'Xóa hình ảnh', enabled=True),
        ], visible=True)

        self._anim_mode = 'open'
        self._anim_t0 = time.perf_counter()
        self.show()
        self.raise_()
        if hasattr(self.view, 'traffic_lights') and self.view.traffic_lights.isVisible():
            self.view.traffic_lights.raise_()
        self.setFocus()
        self._anim_timer.start()

    def close_stage(self, animate: bool = True):
        if self.item is None:
            self.hide()
            return

        self._flush_pending_edits()
        self.stage_toolbar.set_buttons([], visible=False)
        self.right_panel.hide()
        self.group_name_edit.hide()

        if not animate or self._origin_rect.isEmpty():
            self._finish_close()
            return

        self._anim_mode = 'close'
        self._anim_t0 = time.perf_counter()
        self._start_close_rect = QtCore.QRectF(self._current_img_rect)
        self._anim_timer.start()

    def _finish_close(self):
        self._anim_timer.stop()
        self._anim_mode = 'idle'
        self.item = None
        self._display_pixmap = QtGui.QPixmap()
        self.hide()
        self.closed.emit()

    def _flush_pending_edits(self):
        if self.item is None:
            return
        self.filename_widget.commit_edit()
        self._commit_group_name()
        new_note = self.note_edit.toPlainText().strip()
        old_note = getattr(self.item, 'note', '') or ''
        if new_note != old_note:
            self.view.undo_stack.push(
                commands.EditItemNoteCommand(self.item, old_note, new_note))

    def _commit_group_name(self):
        if self.item is None or not getattr(self.item, 'stack_id', None):
            return
        new_name = self.group_name_edit.text().strip()
        cur_name = self.view.scene.stack_manager.get_stack_name(self.item.stack_id)
        if new_name != cur_name:
            self.view.undo_stack.push(
                commands.RenameStackCommand(
                    self.view.scene, self.item.stack_id, cur_name, new_name))

    def _on_filename_renamed(self, new_filename: str):
        if self.item is None:
            return
        old_name = self.item.display_filename
        if new_filename != old_name:
            self.view.undo_stack.push(
                commands.RenameItemFileCommand(self.item, old_name, new_filename))
            DeskboardToast.show_toast(self, f'Đã đổi tên thành {new_filename}')

    def _format_created_date(self, item) -> str:
        ts = getattr(item, 'created_ts', None)
        if not ts:
            sp = getattr(item, '_source_path', None)
            if sp and os.path.exists(sp):
                try:
                    ts = os.path.getctime(sp)
                except OSError:
                    ts = time.time()
            else:
                ts = time.time()
            item.created_ts = ts
        dt = datetime.datetime.fromtimestamp(ts)
        return f'Tạo vào {dt.day:02d} tháng {dt.month:02d}, {dt.year}'

    def apply_theme(self):
        is_dark = (constants.ACTIVE_THEME == 'dark')
        assets = BeeAssets()

        f_hdr = assets.font(11, 700)
        f_val = assets.font(12, 400)
        f_note = assets.font(13, 400)
        f_gname = assets.font(12, 600)

        fg_hdr = '#EDEDEF' if is_dark else '#1A1A1C'
        fg_val = '#9E9FA6' if is_dark else '#6E6F75'
        fg_note = '#EDEDEF' if is_dark else '#1A1A1C'
        gname_fg = '#EDEDEF' if is_dark else '#1A1A1C'
        gname_ph = '#6C6D74' if is_dark else '#A0A1A8'
        gname_line = 'rgba(255,255,255,0.16)' if is_dark else 'rgba(26,26,28,0.15)'

        for hdr in (self.lbl_dim_hdr, self.lbl_file_hdr, self.lbl_date_hdr):
            hdr.setFont(f_hdr)
            hdr.setStyleSheet(f'color: {fg_hdr}; letter-spacing: 0.6px; background: transparent;')

        for val in (self.lbl_dim_val, self.lbl_date_val):
            val.setFont(f_val)
            val.setStyleSheet(f'color: {fg_val}; background: transparent;')

        self.filename_widget.apply_theme(is_dark)

        self.note_edit.setFont(f_note)
        self.note_edit.setStyleSheet(
            f'QPlainTextEdit {{ color: {fg_note}; background: transparent; '
            f'border: none; padding: 0px; selection-background-color: #3A82F7; }}'
        )
        note_pal = self.note_edit.palette()
        note_pal.setColor(QtGui.QPalette.ColorRole.PlaceholderText, QtGui.QColor(gname_ph))
        self.note_edit.setPalette(note_pal)

        self.group_name_edit.setFont(f_gname)
        self.group_name_edit.setStyleSheet(
            f'QLineEdit {{ color: {gname_fg}; background: transparent; '
            f'border: none; border-bottom: 1px solid {gname_line}; '
            f'padding: 2px 2px; selection-background-color: #3A82F7; }}'
            f'QLineEdit:focus {{ border-bottom: 1.5px solid #3A82F7; }}'
        )
        gn_pal = self.group_name_edit.palette()
        gn_pal.setColor(QtGui.QPalette.ColorRole.PlaceholderText, QtGui.QColor(gname_ph))
        self.group_name_edit.setPalette(gn_pal)
        self.update()

    def sync_parent_resize(self, size: QtCore.QSize):
        self.resize(size)
        if self.item is not None:
            self._compute_layout_rects()
            if self._anim_mode == 'idle':
                self._current_img_rect = QtCore.QRectF(self._target_img_rect)
            self.stage_toolbar.sync_parent_resize()
            self.update()

    def _compute_layout_rects(self):
        if self.item is None:
            return
        vw = float(self.width())
        vh = float(self.height())

        # Reserve generous space left (for cover tick + group name + swatches),
        # right (for metadata + note), top, and bottom (for toolbar)
        left_reserve = 165.0
        right_reserve = 268.0
        top_reserve = 64.0
        bot_reserve = 116.0

        avail_w = max(180.0, vw - left_reserve - right_reserve)
        avail_h = max(160.0, vh - top_reserve - bot_reserve)

        iw = max(1.0, float(self.item._orig_width))
        ih = max(1.0, float(self.item._orig_height))
        scale = min(avail_w / iw, avail_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale

        # Optically center between left and right columns
        cx = left_reserve + avail_w * 0.5
        cy = top_reserve + avail_h * 0.5
        self._target_img_rect = QtCore.QRectF(
            cx - draw_w * 0.5,
            cy - draw_h * 0.5,
            draw_w,
            draw_h,
        )

        # Position right metadata + note panel
        rp_x = round(self._target_img_rect.right() + 28.0)
        rp_y = round(self._target_img_rect.top())
        rp_w = min(236, max(160, int(vw - rp_x - 20)))
        rp_h = max(220, round(draw_h))
        self.right_panel.setGeometry(rp_x, rp_y, rp_w, rp_h)

        # Position Group Name small line directly underneath Cover Checkbox on the left
        has_stack = bool(getattr(self.item, 'stack_id', None))
        if has_stack:
            cov_r = self._cover_circle_rect()
            gn_w = min(124, max(80, round(cov_r.right()) - 14))
            gn_x = round(cov_r.right()) - gn_w
            gn_y = round(cov_r.bottom() + 6.0)
            self.group_name_edit.setGeometry(gn_x, gn_y, gn_w, 22)

    def _back_btn_rect(self) -> QtCore.QRectF:
        y = 38.0 if hasattr(self.view, 'traffic_lights') and self.view.traffic_lights.isVisible() else 20.0
        return QtCore.QRectF(20.0, y, 40.0, 40.0)

    def _cover_circle_rect(self) -> QtCore.QRectF:
        r = self._target_img_rect
        return QtCore.QRectF(
            r.left() - 22.0 - self.COVER_DIAM,
            r.top(),
            self.COVER_DIAM,
            self.COVER_DIAM,
        )

    def _swatch_rects(self) -> list[QtCore.QRectF]:
        r = self._target_img_rect
        has_stack = bool(self.item and getattr(self.item, 'stack_id', None))
        # Leave clean space below Cover Checkbox + small Group Name input
        start_y = r.top() + (self.COVER_DIAM + 38.0 if has_stack else 0.0)
        x = r.left() - 22.0 - self.SWATCH_DIAM
        rects = []
        for i in range(len(self._swatches)):
            rects.append(QtCore.QRectF(
                x,
                start_y + i * (self.SWATCH_DIAM + self.SWATCH_GAP),
                self.SWATCH_DIAM,
                self.SWATCH_DIAM,
            ))
        return rects

    def _on_anim_tick(self):
        now = time.perf_counter()
        keep_ticking = False

        if self._cover_pop_t0 > 0:
            dt_pop = now - self._cover_pop_t0
            # Spring pop (420/14) settling from 1.20 -> 1.0
            prog_p = SPRING_POP.value(dt_pop)
            self._cover_scale = 1.20 + (1.0 - 1.20) * prog_p
            if dt_pop < 0.60:
                keep_ticking = True
            else:
                self._cover_scale = 1.0
                self._cover_pop_t0 = -1.0

        if self._anim_mode == 'open':
            dt = now - self._anim_t0
            prog = SPRING_OPEN.value(dt)
            if dt >= 0.50:
                prog = 1.0
            self._backdrop_alpha = min(1.0, dt / 0.22)
            self._chrome_alpha = max(0.0, min(1.0, (dt - 0.12) / 0.22))
            self._current_img_rect = self._lerp_rect(
                self._origin_rect, self._target_img_rect, prog)
            if prog >= 1.0 and self._chrome_alpha >= 1.0:
                self._anim_mode = 'idle'
                self._current_img_rect = QtCore.QRectF(self._target_img_rect)
                self.right_panel.show()
                if self.item and getattr(self.item, 'stack_id', None):
                    self.group_name_edit.show()
            else:
                keep_ticking = True

        elif self._anim_mode == 'close':
            dt = now - self._anim_t0
            prog = SPRING_CLOSE.value(dt)
            if dt >= 0.36:
                prog = 1.0
            self._backdrop_alpha = max(0.0, 1.0 - dt / 0.28)
            self._chrome_alpha = max(0.0, 1.0 - dt / 0.14)
            self._current_img_rect = self._lerp_rect(
                self._start_close_rect, self._origin_rect, prog)
            if prog >= 1.0:
                self._finish_close()
                return
            keep_ticking = True

        self.update()
        if not keep_ticking:
            self._anim_timer.stop()

    @staticmethod
    def _lerp_rect(a: QtCore.QRectF, b: QtCore.QRectF, t: float) -> QtCore.QRectF:
        return QtCore.QRectF(
            a.x() + (b.x() - a.x()) * t,
            a.y() + (b.y() - a.y()) * t,
            a.width() + (b.width() - a.width()) * t,
            a.height() + (b.height() - a.height()) * t,
        )

    def _on_toolbar_action(self, act_id: str):
        if self.item is None:
            return
        if act_id == 'copy':
            clipboard = QtWidgets.QApplication.clipboard()
            self.item.copy_to_clipboard(clipboard)
            DeskboardToast.show_toast(self, 'Đã sao chép hình ảnh')
        elif act_id == 'export':
            default_name = self.item.display_filename
            fn, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                'Xuất hình ảnh',
                default_name,
                'Images (*.png *.jpg *.jpeg)',
            )
            if fn:
                data, _fmt = self.item.pixmap_to_bytes(
                    apply_grayscale=True, apply_crop=True)
                try:
                    with open(fn, 'wb') as f:
                        f.write(data)
                    DeskboardToast.show_toast(
                        self, f'Đã xuất {os.path.basename(fn)}')
                except OSError as e:
                    QtWidgets.QMessageBox.warning(self, 'Lỗi xuất tệp', str(e))
        elif act_id == 'delete':
            target = self.item
            self.close_stage(animate=False)
            self.delete_requested.emit(target)

    def mouseMoveEvent(self, event):
        pos = event.position()
        hb = self._back_btn_rect().contains(pos)
        hc = (
            bool(self.item and getattr(self.item, 'stack_id', None))
            and self._cover_circle_rect().contains(pos)
        )
        hs = -1
        for i, sr in enumerate(self._swatch_rects()):
            if sr.contains(pos):
                hs = i
                break

        if (hb, hc, hs) != (self._hovered_back, self._hovered_cover, self._hovered_swatch):
            self._hovered_back = hb
            self._hovered_cover = hc
            self._hovered_swatch = hs
            if hb or hc or hs >= 0:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
            self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Clear focus from inline edits if clicking stage background
            fw = QtWidgets.QApplication.focusWidget()
            if fw in (self.group_name_edit, self.note_edit, self.filename_widget.line_edit):
                fw.clearFocus()

            pos = event.position()
            if self._back_btn_rect().contains(pos):
                self.close_stage(animate=True)
                event.accept()
                return

            if (self.item is not None
                    and getattr(self.item, 'stack_id', None)
                    and self._cover_circle_rect().contains(pos)):
                if not self.item.is_stack_cover:
                    self.view.undo_stack.push(
                        commands.SetStackCoverCommand(
                            self.view.scene, self.item.stack_id, self.item))
                self._cover_pop_t0 = time.perf_counter()
                self._anim_timer.start()
                DeskboardToast.show_toast(self, 'Đã đặt làm hình đại diện nhóm')
                self.update()
                event.accept()
                return

            for i, sr in enumerate(self._swatch_rects()):
                if sr.contains(pos) and i < len(self._swatches):
                    hex_code = self._swatches[i]
                    QtWidgets.QApplication.clipboard().setText(hex_code)
                    DeskboardToast.show_toast(self, f'Đã sao chép {hex_code}')
                    event.accept()
                    return

        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_stage(animate=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)

        is_dark = (constants.ACTIVE_THEME == 'dark')
        bg_col = QtGui.QColor('#1B1C1E') if is_dark else QtGui.QColor('#FFFFFF')
        bg_col.setAlphaF(max(0.0, min(1.0, self._backdrop_alpha)))
        p.fillRect(self.rect(), bg_col)

        # 1. Center Hero Artwork
        if not self._display_pixmap.isNull() and not self._current_img_rect.isEmpty():
            # Crop-aware source rect
            pm = self._display_pixmap
            if self.item is not None and self.item._orig_width > 0 and self.item._orig_height > 0:
                sx = pm.width() / self.item._orig_width
                sy = pm.height() / self.item._orig_height
                c = self.item.crop
                src_r = QtCore.QRectF(
                    c.x() * sx, c.y() * sy, c.width() * sx, c.height() * sy)
            else:
                src_r = QtCore.QRectF(0, 0, pm.width(), pm.height())
            p.drawPixmap(self._current_img_rect, pm, src_r)

        if self._chrome_alpha <= 0.01 or self.item is None:
            p.end()
            return

        p.setOpacity(self._chrome_alpha)
        assets = BeeAssets()
        ink = QtGui.QColor('#EDEDEF') if is_dark else QtGui.QColor('#1A1A1C')

        # 2. Top-Left Back Button (`<-`)
        br = self._back_btn_rect()
        if self._hovered_back:
            hov_bg = QtGui.QColor(255, 255, 255, 22) if is_dark else QtGui.QColor(0, 0, 0, 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(hov_bg)
            p.drawEllipse(br)
        arr_pm = assets.svg_icon_pixmap('arrow-left', size=20, color=ink)
        p.drawPixmap(
            QtCore.QPointF(br.center().x() - 10.0, br.center().y() - 10.0),
            arr_pm,
        )

        # 3. Left Column: Cover Radio-Checkbox (`28x28px`)
        if getattr(self.item, 'stack_id', None):
            cr = self._cover_circle_rect()
            p.save()
            p.translate(cr.center())
            sc = self._cover_scale * (1.08 if self._hovered_cover else 1.0)
            p.scale(sc, sc)
            local_cr = QtCore.QRectF(
                -self.COVER_DIAM * 0.5,
                -self.COVER_DIAM * 0.5,
                self.COVER_DIAM,
                self.COVER_DIAM,
            )
            is_cov = bool(self.item.is_stack_cover)
            if is_cov:
                p.setBrush(QtGui.QColor('#FFDA12'))
                p.setPen(QtGui.QPen(QtGui.QColor('#E5C100'), 1.5))
                p.drawEllipse(local_cr)
                ck_pen = QtGui.QPen(QtGui.QColor('#1A1A1C'), 2.2)
            else:
                c_bg = QtGui.QColor('#2C2D30') if is_dark else QtGui.QColor('#FFFFFF')
                c_rim = (
                    QtGui.QColor(255, 255, 255, 110 if self._hovered_cover else 65)
                    if is_dark
                    else QtGui.QColor(26, 26, 28, 120 if self._hovered_cover else 65)
                )
                p.setBrush(c_bg)
                p.setPen(QtGui.QPen(c_rim, 1.5))
                p.drawEllipse(local_cr)
                ck_col = QtGui.QColor(ink)
                ck_col.setAlpha(130 if self._hovered_cover else 64)
                ck_pen = QtGui.QPen(ck_col, 1.9)

            ck_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            ck_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(ck_pen)
            p.drawLine(QtCore.QPointF(-5.2, 0.4), QtCore.QPointF(-1.4, 4.2))
            p.drawLine(QtCore.QPointF(-1.4, 4.2), QtCore.QPointF(5.6, -3.6))
            p.restore()

            if self._hovered_cover:
                tip_txt = (
                    'Đang là hình đại diện nhóm'
                    if is_cov else 'Đặt làm hình đại diện nhóm'
                )
                f_tip = assets.font(11, 600)
                fm = QtGui.QFontMetrics(f_tip)
                tw = fm.horizontalAdvance(tip_txt) + 18
                tip_r = QtCore.QRectF(cr.left(), cr.top() - 32.0, float(tw), 24.0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor('#16181A'))
                p.drawRoundedRect(tip_r, 7.0, 7.0)
                p.setFont(f_tip)
                p.setPen(QtGui.QColor('#F5F6F7'))
                p.drawText(tip_r, int(Qt.AlignmentFlag.AlignCenter), tip_txt)

        # 4. Left Column: 5 Dominant Color Swatches
        sw_rects = self._swatch_rects()
        swatch_rim = (
            QtGui.QColor(255, 255, 255, 36)
            if is_dark else QtGui.QColor(0, 0, 0, 24)
        )
        for idx, (sr, hex_code) in enumerate(zip(sw_rects, self._swatches)):
            p.save()
            p.translate(sr.center())
            if idx == self._hovered_swatch:
                p.scale(1.13, 1.13)
            local_sr = QtCore.QRectF(
                -self.SWATCH_DIAM * 0.5,
                -self.SWATCH_DIAM * 0.5,
                self.SWATCH_DIAM,
                self.SWATCH_DIAM,
            )
            p.setBrush(QtGui.QColor(hex_code))
            p.setPen(QtGui.QPen(swatch_rim, 1.0))
            p.drawEllipse(local_sr)
            p.restore()

            if idx == self._hovered_swatch:
                f_hex = assets.font(11, 600)
                fm = QtGui.QFontMetrics(f_hex)
                tw = fm.horizontalAdvance(hex_code) + 16
                hr = QtCore.QRectF(
                    sr.left() - tw - 8.0,
                    sr.center().y() - 12.0,
                    float(tw),
                    24.0,
                )
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor('#16181A'))
                p.drawRoundedRect(hr, 7.0, 7.0)
                p.setFont(f_hex)
                p.setPen(QtGui.QColor('#F5F6F7'))
                p.drawText(hr, int(Qt.AlignmentFlag.AlignCenter), hex_code)

        p.end()
