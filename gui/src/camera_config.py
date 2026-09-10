"""camera_config.py — universal proxy-camera / simulation settings.

Loaded once from camera.config (JSON), independent of whichever flight-region
config is passed to new-gui.py, since the camera feature applies uniformly
across regions rather than varying per region.
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CameraConfig:
    # Master switch — proxy cameras exist only when this is true.
    simulation: bool = False

    # Field of view of the simulated nadir camera.
    fov_h_deg: float = 80.0
    fov_v_deg: float = 60.0

    # Zoom-in only: 1.0 = the configured FOV, higher narrows the footprint.
    default_zoom: float = 1.0
    max_zoom: float = 6.0
    zoom_step: float = 1.5   # multiplier applied per Zoom In / Zoom Out click

    # Capture cadence while streaming.
    streaming_interval_s: float = 0.3

    # Output frame size in pixels.
    image_px: int = 320

    # JPEG quality for frames published over MQTT (0-100). Tunable
    # independently of image_px so payload size can be reined in without
    # degrading the on-screen resolution.
    jpeg_quality: int = 75
    camera_topic_template: str = "VIDEO_STREAM/{name}/frame"

    @classmethod
    def from_file(cls, path: str) -> "CameraConfig":
        """Load JSON config; missing file just yields all-default (simulation off)."""
        p = Path(path)
        if not p.exists():
            return cls()
        with open(p, "r") as f:
            raw = json.load(f)

        return cls(
            simulation=bool(raw.get("simulation", False)),
            fov_h_deg=float(raw.get("fov_h_deg", 80.0)),
            fov_v_deg=float(raw.get("fov_v_deg", 60.0)),
            default_zoom=float(raw.get("default_zoom", 1.0)),
            max_zoom=float(raw.get("max_zoom", 6.0)),
            zoom_step=float(raw.get("zoom_step", 1.5)),
            streaming_interval_s=float(raw.get("streaming_interval_s", 0.3)),
            image_px=int(raw.get("image_px", 320)),
            jpeg_quality=int(raw.get("jpeg_quality", 75)),
            camera_topic_template=raw.get("camera_topic_template", "VIDEO_STREAM/{name}/frame"),
        )
