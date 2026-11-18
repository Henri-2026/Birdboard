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

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import logging
import os
import time

from PyQt6 import QtCore

from beeref.fileio.errors import BeeFileIOError
from beeref.fileio.image import load_image, load_image_lod  # noqa: F401
from beeref.fileio.sql import SQLiteIO, is_bee_file


__all__ = [
    'is_bee_file',
    'load_bee',
    'save_bee',
    'load_images',
    'ThreadedIO',
    'BeeFileIOError',
]

logger = logging.getLogger(__name__)


def load_bee(filename, scene, worker=None):
    """Load BeeRef native file."""
    logger.info(f'Loading from file {filename}...')
    io = SQLiteIO(filename, scene, readonly=True, worker=worker)
    return io.read()


def save_bee(filename, scene, create_new=False, worker=None):
    """Save BeeRef native file."""
    logger.info(f'Saving to file {filename}...')
    logger.debug(f'Create new: {create_new}')
    io = SQLiteIO(filename, scene, create_new, worker=worker)
    io.write()
    logger.info('End save')


def load_images(filenames, pos, scene, worker):
    """Parallel multi-core image loader with batched GUI updates (zero lag at 1000+ images)."""
    total = len(filenames)
    errors = []
    if worker:
        worker.begin_processing.emit(total)

    if total == 0:
        if worker:
            worker.finished.emit('', errors)
        return

    max_workers = max(4, min(16, (os.cpu_count() or 4) * 2))
    # Bounded window of in-flight tasks so memory stays flat even at 10,000 files
    max_in_flight = max_workers * 4

    done_count = 0
    last_emit_time = time.perf_counter()

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix='BirdboardImport'
    ) as pool:
        it = iter(enumerate(filenames))
        in_flight = {}

        # Prime initial window
        for _ in range(min(total, max_in_flight)):
            try:
                idx, fn = next(it)
                in_flight[pool.submit(load_image_lod, fn)] = (idx, fn)
            except StopIteration:
                break

        while in_flight:
            if worker and worker.canceled:
                for fut in in_flight:
                    fut.cancel()
                break

            completed, _ = wait(
                in_flight.keys(), timeout=0.05, return_when=FIRST_COMPLETED)

            for fut in completed:
                idx, orig_fn = in_flight.pop(fut)
                try:
                    payload, resolved_fn = fut.result()
                except Exception:
                    logger.exception(f'Error loading image {orig_fn}')
                    payload, resolved_fn = None, str(orig_fn)

                done_count += 1
                if payload is None:
                    errors.append(str(resolved_fn))
                else:
                    scene.add_item_later(
                        {
                            'type': 'pixmap',
                            'payload': payload,
                            'data': {'filename': resolved_fn},
                            'center_pos': pos,
                            'order_idx': idx,
                        },
                        selected=True,
                    )

                # Refill sliding window
                if not (worker and worker.canceled):
                    try:
                        next_idx, next_fn = next(it)
                        in_flight[pool.submit(load_image_lod, next_fn)] = (
                            next_idx, next_fn)
                    except StopIteration:
                        pass

            # Throttle cross-thread Qt signal emissions (~25 Hz) so GUI stays 60 FPS
            now = time.perf_counter()
            if worker and (now - last_emit_time >= 0.04 or not in_flight):
                worker.progress.emit(done_count)
                last_emit_time = now

    if worker:
        worker.finished.emit('', errors)


class ThreadedIO(QtCore.QThread):
    """Dedicated thread for loading and saving."""

    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str, list)
    begin_processing = QtCore.pyqtSignal(int)
    user_input_required = QtCore.pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.kwargs['worker'] = self
        self.canceled = False

    def run(self):
        self.func(*self.args, **self.kwargs)

    def on_canceled(self):
        self.canceled = True
