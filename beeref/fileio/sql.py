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

"""Birdboard (based on BeeRef) SQLite file I/O with instant LOD thumbnail cache
and single-transaction atomic writes.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import pathlib
import shutil
import sqlite3
import tempfile
import time

from beeref import constants
from beeref.items import BeeErrorItem
from beeref.lod_cache import (
    LODImagePayload,
    build_payload_from_bytes,
    decode_from_bytes,
)
from .errors import BeeFileIOError, IMG_LOADING_ERROR_MSG
from .schema import SCHEMA, USER_VERSION, MIGRATIONS, APPLICATION_ID


logger = logging.getLogger(__name__)

THUMB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lod_thumbs (
    item_id INTEGER PRIMARY KEY,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    fmt TEXT DEFAULT '',
    thumb BLOB NOT NULL
)
"""


def is_bee_file(path):
    """Check whether the file at the given path is a bee file."""
    return os.path.splitext(path)[1].lower() == '.bee'


def handle_sqlite_errors(func):
    def wrapper(self, *args, **kwargs):
        try:
            func(self, *args, **kwargs)
        except Exception as e:
            logger.exception(f'Error while reading/writing {self.filename}')
            try:
                if (hasattr(self, '_connection')
                        and self._connection.in_transaction):
                    self.ex('ROLLBACK')
                    logger.debug('Transaction rolled back')
            except sqlite3.Error:
                pass
            self._close_connection()
            self._cleanup_staging()
            if self.worker:
                self.worker.finished.emit(self.filename, [str(e)])
            else:
                raise BeeFileIOError(msg=str(e), filename=self.filename) from e

    return wrapper


class SQLiteIO:

    def __init__(self, filename, scene, create_new=False, readonly=False,
                 worker=None):
        self.scene = scene
        self.create_new = create_new
        self.filename = filename
        self.readonly = readonly
        self.worker = worker
        self.retry = False
        self._staging_path: str | None = None

    def __del__(self):
        self._close_connection()
        self._cleanup_staging()

    def _cleanup_staging(self):
        if self._staging_path and os.path.exists(self._staging_path):
            try:
                os.remove(self._staging_path)
            except OSError:
                pass
            self._staging_path = None

    def _close_connection(self):
        if hasattr(self, '_connection'):
            self._connection.close()
            delattr(self, '_connection')
        if hasattr(self, '_cursor'):
            delattr(self, '_cursor')
        if hasattr(self, '_tmpdir'):
            self._tmpdir.cleanup()
            delattr(self, '_tmpdir')

    def _establish_connection(self):
        target_file = self.filename

        if self.create_new and not self.readonly:
            if os.path.exists(self.filename):
                # Write to staging file first so lazy reads from existing
                # self.filename never break when overwriting the same file!
                parent_dir = os.path.dirname(os.path.abspath(self.filename))
                fd, staging = tempfile.mkstemp(
                    prefix='.birdboard_save_', suffix='.bee', dir=parent_dir)
                os.close(fd)
                os.remove(staging)
                self._staging_path = staging
                target_file = staging

        uri = pathlib.Path(target_file).resolve().as_uri()
        if self.readonly:
            uri = f'{uri}?mode=rw'
        self._connection = sqlite3.connect(uri, uri=True)
        self._cursor = self._connection.cursor()
        if not self.readonly:
            self._cursor.execute('PRAGMA synchronous = NORMAL')
            self._cursor.execute('PRAGMA temp_store = MEMORY')

        if not self.create_new:
            try:
                self._migrate()
            except Exception:
                logger.exception('Error migrating bee file')
                self.create_new = True
                self._close_connection()
                self._establish_connection()

    def _migrate(self):
        """Migrate database if necessary."""
        version = self.fetchone('PRAGMA user_version')[0]
        if version >= USER_VERSION:
            return

        if self.readonly:
            try:
                self.ex('PRAGMA application_id=%s' % APPLICATION_ID)
            except sqlite3.Error:
                self._connection.close()
                self._tmpdir = tempfile.TemporaryDirectory(
                    prefix=constants.APPNAME)
                tmpname = os.path.join(self._tmpdir.name, 'mig.bee')
                shutil.copyfile(self.filename, tmpname)
                self._connection = sqlite3.connect(tmpname)
                self._cursor = self.connection.cursor()

        self.ex('BEGIN TRANSACTION')
        for i in range(version, USER_VERSION):
            for migration in MIGRATIONS[i + 1]:
                self.ex(migration)
        self.write_meta()
        self.connection.commit()

    @property
    def connection(self):
        if not hasattr(self, '_connection'):
            self._establish_connection()
        return self._connection

    @property
    def cursor(self):
        if not hasattr(self, '_cursor'):
            self._establish_connection()
        return self._cursor

    def ex(self, *args, **kwargs):
        return self.cursor.execute(*args, **kwargs)

    def exmany(self, *args, **kwargs):
        return self.cursor.executemany(*args, **kwargs)

    def fetchone(self, *args, **kwargs):
        self.ex(*args, **kwargs)
        return self.cursor.fetchone()

    def fetchall(self, *args, **kwargs):
        self.ex(*args, **kwargs)
        return self.cursor.fetchall()

    def write_meta(self):
        self.ex('PRAGMA application_id=%s' % APPLICATION_ID)
        self.ex('PRAGMA user_version=%s' % USER_VERSION)
        self.ex('PRAGMA foreign_keys=ON')

    def create_schema_on_new(self):
        if self.create_new:
            self.write_meta()
            for schema in SCHEMA:
                self.ex(schema)
        self.ex(THUMB_TABLE_SQL)

    def _has_thumb_table(self) -> bool:
        row = self.fetchone(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='lod_thumbs'")
        return row is not None

    @handle_sqlite_errors
    def read(self):
        resolved_bee_path = os.path.abspath(self.filename)
        has_thumbs = self._has_thumb_table()

        if has_thumbs:
            # Fast path: load tiny cached thumbnails (~15 KB/item) without
            # reading multi-gigabyte sqlar full-res BLOBs from disk!
            meta_rows = self.fetchall(
                'SELECT items.id, items.type, items.x, items.y, items.z, '
                'items.scale, items.rotation, items.flip, items.data, '
                'lod_thumbs.width, lod_thumbs.height, lod_thumbs.fmt, '
                'lod_thumbs.thumb '
                'FROM items '
                'LEFT JOIN lod_thumbs ON lod_thumbs.item_id = items.id')
        else:
            meta_rows = self.fetchall(
                'SELECT items.id, items.type, items.x, items.y, items.z, '
                'items.scale, items.rotation, items.flip, items.data, '
                'NULL, NULL, NULL, NULL '
                'FROM items')

        total = len(meta_rows)
        if self.worker:
            self.worker.begin_processing.emit(total)

        if total == 0:
            if self.worker:
                self.worker.finished.emit(self.filename, [])
            return

        # Identify pixmap items missing cached thumbnails (e.g. legacy .bee file)
        missing_ids = [
            r[0] for r in meta_rows
            if r[1] == 'pixmap' and r[12] is None
        ]

        # Pre-decode fast thumbnails in parallel for instant startup
        decoded_payloads: dict[int, LODImagePayload | None] = {}
        max_workers = max(4, min(12, (os.cpu_count() or 4) * 2))
        last_emit = time.perf_counter()
        done_count = 0

        def _decode_cached_thumb(row_tuple):
            item_id, w, h, fmt, thumb_blob = row_tuple
            img, *_ = decode_from_bytes(thumb_blob, max_edge=None)
            if img.isNull() or not w or not h:
                return item_id, None
            return item_id, LODImagePayload(
                thumb_image=img,
                orig_width=int(w),
                orig_height=int(h),
                img_format=fmt or '',
                bee_source=(resolved_bee_path, item_id),
                full_image=img if max(int(w), int(h)) <= max(img.width(), img.height()) else None,
            )

        cached_tasks = [
            (r[0], r[9], r[10], r[11], r[12])
            for r in meta_rows
            if r[1] == 'pixmap' and r[12] is not None
        ]

        if cached_tasks:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for item_id, payload in pool.map(_decode_cached_thumb, cached_tasks):
                    decoded_payloads[item_id] = payload

        # Fallback for legacy .bee items without lod_thumbs: stream in chunks
        # so we never pull 3 GB of BLOBs into RAM simultaneously.
        if missing_ids:
            CHUNK = 64
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for start in range(0, len(missing_ids), CHUNK):
                    if self.worker and self.worker.canceled:
                        self.worker.finished.emit('', [])
                        return
                    batch_ids = missing_ids[start:start + CHUNK]
                    placeholders = ','.join('?' for _ in batch_ids)
                    blob_rows = self.fetchall(
                        f'SELECT item_id, data FROM sqlar '
                        f'WHERE item_id IN ({placeholders})',
                        batch_ids,
                    )

                    def _decode_full_blob(b_row):
                        iid, raw_blob = b_row
                        if not raw_blob:
                            return iid, None
                        pl = build_payload_from_bytes(
                            raw_blob,
                            bee_source=(resolved_bee_path, iid),
                            keep_bytes=False,
                        )
                        return iid, pl

                    for iid, pl in pool.map(_decode_full_blob, blob_rows):
                        decoded_payloads[iid] = pl

        # Queue all items in clean batches without msleep(10)
        for i, row in enumerate(meta_rows):
            if self.worker and self.worker.canceled:
                self.worker.finished.emit('', [])
                return

            save_id = row[0]
            typ = row[1]
            extra = json.loads(row[8]) if row[8] else {}
            data = {
                'save_id': save_id,
                'type': typ,
                'x': row[2],
                'y': row[3],
                'z': row[4],
                'scale': row[5],
                'rotation': row[6],
                'flip': row[7],
                'data': extra,
            }

            if typ == 'pixmap':
                payload = decoded_payloads.get(save_id)
                if payload is None:
                    fname = extra.get('filename', '')
                    data['type'] = BeeErrorItem.TYPE
                    data['data'] = {
                        'text': (f'Image could not be loaded: {fname}\n'
                                 + IMG_LOADING_ERROR_MSG)
                    }
                else:
                    data['payload'] = payload

            self.scene.add_item_later(data)
            done_count = i + 1

            now = time.perf_counter()
            if self.worker and (now - last_emit >= 0.04 or done_count == total):
                self.worker.progress.emit(done_count)
                last_emit = now

        if self.worker:
            self.worker.finished.emit(self.filename, [])

    @handle_sqlite_errors
    def write(self):
        if self.readonly:
            raise sqlite3.OperationalError(
                'Attempt to write to a readonly database')
        try:
            self.create_schema_on_new()
            self.write_data()
        except Exception:
            if self.retry:
                raise
            else:
                self.retry = True
                logger.exception(
                    f'Updating existing file {self.filename} failed; recreating')
                self.create_new = True
                self._close_connection()
                self._cleanup_staging()
                self.write()

    def write_data(self):
        # Clear save_ids AFTER establishing staging connection so existing
        # _bee_source links remain readable during Save As overwrite!
        if self.create_new:
            to_delete = set()
        else:
            to_delete = {
                row[0] for row in self.fetchall('SELECT id FROM items')
            }
            keep = {
                item.original_save_id
                for item in self.scene.items_by_type(BeeErrorItem.TYPE)
            }
            to_delete = to_delete - keep

        to_save = list(self.scene.items_for_save())
        total = len(to_save)
        if self.worker:
            self.worker.begin_processing.emit(total)

        existing_thumbs = {
            row[0] for row in self.fetchall('SELECT item_id FROM lod_thumbs')
        }

        last_emit = time.perf_counter()
        new_save_ids: list[tuple[object, int]] = []

        # Single atomic transaction instead of 1,000+ slow disk commits!
        self.ex('BEGIN TRANSACTION')
        for i, item in enumerate(to_save):
            if self.worker and self.worker.canceled:
                self.ex('ROLLBACK')
                self._close_connection()
                self._cleanup_staging()
                self.worker.finished.emit(self.filename, [])
                return

            if not self.create_new and item.save_id and item.save_id in to_delete:
                self.update_item(item, has_thumb=(item.save_id in existing_thumbs))
                to_delete.remove(item.save_id)
                new_save_ids.append((item, item.save_id))
            else:
                sid = self.insert_item(item)
                new_save_ids.append((item, sid))

            now = time.perf_counter()
            if self.worker and (now - last_emit >= 0.04 or i + 1 == total):
                self.worker.progress.emit(i + 1)
                last_emit = now

        if to_delete:
            self.delete_items(to_delete)

        self.connection.commit()

        # Only run VACUUM if items were actually deleted
        if to_delete:
            self.ex('VACUUM')
            self.connection.commit()

        self._close_connection()

        # Atomically swap staging file into place if overwriting
        if self._staging_path and os.path.exists(self._staging_path):
            os.replace(self._staging_path, self.filename)
            self._staging_path = None

        resolved_path = os.path.abspath(self.filename)
        for item, sid in new_save_ids:
            item.save_id = sid
            if hasattr(item, 'set_bee_source'):
                item.set_bee_source(resolved_path, sid)

        if self.worker:
            self.worker.finished.emit(self.filename, [])

    def delete_items(self, to_delete):
        params = [(pk,) for pk in to_delete]
        self.exmany('DELETE FROM items WHERE id=?', params)
        self.exmany('DELETE FROM sqlar WHERE item_id=?', params)
        self.exmany('DELETE FROM lod_thumbs WHERE item_id=?', params)

    def insert_item(self, item) -> int:
        self.ex(
            'INSERT INTO items (type, x, y, z, scale, rotation, flip, data) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (item.TYPE, item.pos().x(), item.pos().y(), item.zValue(),
             item.scale(), item.rotation(), item.flip(),
             json.dumps(item.get_extra_save_data())))
        new_id = self.cursor.lastrowid

        if hasattr(item, 'pixmap_to_bytes'):
            pixmap_bytes, imgformat = item.pixmap_to_bytes()
            name = item.get_filename_for_export(
                imgformat, save_id_default=new_id)
            self.ex(
                'INSERT INTO sqlar (item_id, name, mode, sz, data) '
                'VALUES (?, ?, ?, ?, ?)',
                (new_id, name, 0o644, len(pixmap_bytes), pixmap_bytes))

            if hasattr(item, 'get_thumb_save_bytes'):
                thumb_bytes = item.get_thumb_save_bytes()
                if thumb_bytes:
                    self.ex(
                        'INSERT OR REPLACE INTO lod_thumbs '
                        '(item_id, width, height, fmt, thumb) '
                        'VALUES (?, ?, ?, ?, ?)',
                        (new_id, item.orig_size.width(),
                         item.orig_size.height(), imgformat, thumb_bytes))
        return new_id

    def update_item(self, item, has_thumb=True):
        self.ex(
            'UPDATE items SET x=?, y=?, z=?, scale=?, rotation=?, flip=?, '
            'data=? WHERE id=?',
            (item.pos().x(), item.pos().y(), item.zValue(), item.scale(),
             item.rotation(), item.flip(),
             json.dumps(item.get_extra_save_data()),
             item.save_id))
        if not has_thumb and hasattr(item, 'get_thumb_save_bytes'):
            thumb_bytes = item.get_thumb_save_bytes()
            if thumb_bytes:
                self.ex(
                    'INSERT OR REPLACE INTO lod_thumbs '
                    '(item_id, width, height, fmt, thumb) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (item.save_id, item.orig_size.width(),
                     item.orig_size.height(), '', thumb_bytes))
