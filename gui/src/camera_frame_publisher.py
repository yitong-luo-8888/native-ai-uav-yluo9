"""camera_frame_publisher.py — publishes each captured camera frame over MQTT.

Bridges CameraManager.frame_updated to DroneStore's MQTT client. The frame
is already scene-object-composited (see tile_map.py composite_nadir_crop),
so this only encodes and publishes it -- one capture, one publish, reusing
CameraManager's own streaming_interval_s throttle.
"""

import json
import time

from camera_config import CameraConfig
from camera_manager import CameraManager
from drone_store import DroneStore
from image_codec import pixmap_to_jpeg_b64


class CameraFramePublisher:
    def __init__(self, camera_manager: CameraManager, drone_store: DroneStore, cfg: CameraConfig) -> None:
        self._camera_manager = camera_manager
        self._drone_store = drone_store
        self._cfg = cfg
        camera_manager.frame_updated.connect(self._on_frame_updated)

    def _on_frame_updated(self, name: str) -> None:
        pixmap = self._camera_manager.get_frame(name)
        if pixmap is None or pixmap.isNull():
            return
        envelope = {
            "drone": name,
            "timestamp": time.time(),
            "format": "jpeg",
            "image_b64": pixmap_to_jpeg_b64(pixmap, self._cfg.jpeg_quality),
        }
        topic = self._cfg.camera_topic_template.format(name=name)
        self._drone_store.publish(topic, json.dumps(envelope))
