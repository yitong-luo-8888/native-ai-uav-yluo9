"""candidates.build_candidates: the response menu and the R2 low-confidence policy."""
from planner.candidates import build_candidates
from planner.config import parse_config
from planner.person_registry import PersonRegistry
from planner.world_model import WorldModel


def types(menu):
    return [c.type for c in menu]


def test_low_conf_no_deliver(world):
    """R2: confidence 0.31 (the class-frame false positive) must not offer deliver."""
    menu = build_candidates(0.31, world)
    assert types(menu) == ["hover_stream", "circle_stream"]


def test_high_conf_has_deliver(world):
    """R2/R4: confidence 0.80 offers hover_stream, circle_stream and deliver."""
    assert types(build_candidates(0.80, world)) == ["hover_stream", "circle_stream", "deliver"]


def test_parameters_come_from_config(world, config):
    """R4: hover_stream defaults are mission_config.json's hover_standoff_m and stream_duration_s."""
    hover = next(c for c in build_candidates(0.8, world) if c.type == "hover_stream")
    assert hover.parameters["standoff_m"] == config.defaults.hover_standoff_m == 10
    assert hover.parameters["duration_s"] == config.defaults.stream_duration_s == 60
    circle = next(c for c in build_candidates(0.8, world) if c.type == "circle_stream")
    assert circle.parameters["radius_m"] == config.defaults.circle_radius_m


def test_deliver_options_include_kit(world):
    """R4: deliver offers an item choice that includes medical_kit."""
    deliver = next(c for c in build_candidates(0.8, world) if c.type == "deliver")
    assert "medical_kit" in deliver.options["item"]
    assert deliver.parameters["item"] == "medical_kit"


def test_eligible_uavs_respect_payload():
    """R4: a drone without the kit is not eligible for deliver."""
    raw = {"owned_uavs": ["1", "2"], "payloads": {"1": [], "2": ["medical_kit"]},
           "battery": {"reserve": 0.25, "cost": {"deliver": 0.1, "circle_stream": 0.08, "hover_stream": 0.05}},
           "defaults": {"transit_alt_m": 20, "delivery_alt_m": 5, "delivery_dwell_s": 5, "circle_radius_m": 15,
                        "circle_speed_mps": 3, "stream_duration_s": 60, "hover_standoff_m": 10},
           "missions": {}}
    world = WorldModel(parse_config(raw), PersonRegistry())
    menu = {c.type: c for c in build_candidates(0.9, world)}
    assert menu["deliver"].eligible_uavs == ["2"]
    assert menu["deliver"].default_uav == "2"
    assert menu["hover_stream"].eligible_uavs == ["1", "2"]
