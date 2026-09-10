import json
from dataclasses import dataclass


@dataclass
class MapConfig:
    # ---- MQTT ----
    broker: str = "localhost"
    port: int = 1883
    topic: str = "update_drone"

    # ---- Window ----
    windowed: bool = False
    width: int = 1280
    height: int = 720

    # ---- Panel ----
    show_panel: bool = True
    panel_side: str = "right"   # "left" | "right" | "top" | "bottom"

    # ---- Tick ----
    tick_rate_ms: int = 8

    # ---- Drone state ----
    base_elevation: float = 0.0
    base_elev_tol_m: float = 0.5
    default_phys_h_m: float = 4.0

    @classmethod
    def from_file(cls, path: str) -> "MapConfig":
        """Load JSON config and return a MapConfig instance."""
        with open(path, "r") as f:
            raw = json.load(f)

        return cls(
            broker=raw.get("broker", "localhost"),
            port=int(raw.get("port", 1883)),
            topic=raw.get("topic", "update_drone"),

            windowed=bool(raw.get("windowed", False)),
            width=int(raw.get("width", 1280)),
            height=int(raw.get("height", 720)),

            show_panel=bool(raw.get("show_panel", True)),
            panel_side=str(raw.get("panel_side", "right")),

            tick_rate_ms=int(raw.get("tick_rate_ms", 33)),

            base_elevation=float(raw.get("base_elevation", 0.0)),
            base_elev_tol_m=float(raw.get("base_elev_tol_m", 0.5)),
            default_phys_h_m=float(raw.get("default_phys_h_m", 4.0)),
        )
