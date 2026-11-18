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

import logging
import os.path
import tempfile
from urllib.error import URLError
from urllib import parse, request

from PyQt6 import QtGui
from lxml import etree

from beeref.lod_cache import (
    LODImagePayload,
    build_payload_from_bytes,
    build_payload_from_path,
    decode_from_path,
)


logger = logging.getLogger(__name__)


def exif_rotated_image(path=None):
    """Returns a QImage transformed according to EXIF orientation via C++ QImageReader."""
    if not path:
        return QtGui.QImage()
    img, *_ = decode_from_path(path, max_edge=None)
    return img


def load_image(path):
    """Legacy full-image loader kept for compatibility."""
    if isinstance(path, str):
        path = os.path.normpath(path)
        return (exif_rotated_image(path), path)
    if path.isLocalFile():
        path = os.path.normpath(path.toLocalFile())
        return (exif_rotated_image(path), path)

    url = bytes(path.toEncoded()).decode()
    domain = '.'.join(parse.urlparse(url).netloc.split(".")[-2:])
    img = QtGui.QImage()
    if domain == 'pinterest.com':
        try:
            page_data = request.urlopen(url).read()
            root = etree.HTML(page_data)
            url = root.xpath("//img")[0].get('src')
        except Exception as e:
            logger.debug(f'Pinterest image download failed: {e}')
    try:
        imgdata = request.urlopen(url).read()
    except URLError as e:
        logger.debug(f'Downloading image failed: {e.reason}')
    else:
        with tempfile.TemporaryDirectory() as tmp:
            fname = os.path.join(tmp, 'img')
            with open(fname, 'wb') as f:
                f.write(imgdata)
            img = exif_rotated_image(fname)
    return (img, url)


def load_image_lod(path) -> tuple[LODImagePayload | None, str]:
    """Thread-safe fast LOD loader for massive multi-image imports."""
    if isinstance(path, str):
        norm = os.path.normpath(path)
        return (build_payload_from_path(norm), norm)

    if path.isLocalFile():
        norm = os.path.normpath(path.toLocalFile())
        return (build_payload_from_path(norm), norm)

    url = bytes(path.toEncoded()).decode()
    domain = '.'.join(parse.urlparse(url).netloc.split(".")[-2:])
    if domain == 'pinterest.com':
        try:
            page_data = request.urlopen(url).read()
            root = etree.HTML(page_data)
            url = root.xpath("//img")[0].get('src')
        except Exception as e:
            logger.debug(f'Pinterest image download failed: {e}')
    try:
        imgdata = request.urlopen(url).read()
    except Exception as e:
        logger.debug(f'Downloading image failed: {e}')
        return (None, url)

    payload = build_payload_from_bytes(imgdata, keep_bytes=True)
    return (payload, url)
