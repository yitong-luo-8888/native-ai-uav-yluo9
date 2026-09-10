"""image_codec.py — QPixmap -> base64 JPEG conversion for MQTT payloads."""

import base64

from PyQt5.QtCore import QBuffer, QIODevice
from PyQt5.QtGui import QPixmap


def pixmap_to_jpeg_b64(pixmap: QPixmap, quality: int = 75) -> str:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "JPG", quality)
    return base64.b64encode(bytes(buf.data())).decode("ascii")
