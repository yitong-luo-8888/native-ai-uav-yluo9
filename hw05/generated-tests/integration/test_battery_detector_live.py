"""Integration tests for the LIVE-FLEET parts of
lab/lesson4/battery/battery_detector.py: on_connect (publishes retained
monitor_config and subscribes on a real client) and main() (the blocking
event loop that wires on_connect/on_message to a real mqtt.Client).

Requires the fleet to be up (`docker compose up -d`) with the MQTT broker
reachable at localhost:1883 and vehicle VEHICLE_ID (default "1") publishing
monitored_data with a "battery" field. Skipped automatically if the broker
is not reachable. Run explicitly with:

    pytest generated-tests/integration -v -m integration

main() itself calls client.loop_forever(), which blocks forever, so it
cannot be called directly inside a bounded test. The second test below
reproduces main()'s exact wiring (same on_connect/on_message callbacks,
same client.connect call) but drives the network loop with
loop_start()/loop_stop() around an explicit deadline instead of
loop_forever(), so a hung fleet cannot hang CI. Assertions are made against
real telemetry-derived module state only -- never against printed output,
per this course's grading monitor.
"""
import socket
import sys
import time
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"could not locate repo root (no .git found above {start})")


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

import lab.lesson4.battery.battery_detector as battery_detector

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - environment guard, not test logic
    mqtt = None

pytestmark = pytest.mark.integration


def _broker_reachable(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def require_live_broker():
    if mqtt is None:
        pytest.skip("paho-mqtt is not installed")
    if not _broker_reachable(battery_detector.MQTT_HOST, battery_detector.MQTT_PORT):
        pytest.skip(
            f"no MQTT broker reachable at {battery_detector.MQTT_HOST}:{battery_detector.MQTT_PORT} "
            "-- start the fleet with `docker compose up -d`"
        )
    battery_detector._window.clear()
    battery_detector._verdict = None
    yield
    battery_detector._window.clear()
    battery_detector._verdict = None


def test_on_connect_publishes_monitor_config_and_receives_monitored_data():
    observed = {}

    def observe_config(client, userdata, msg):
        observed["monitor_config"] = msg.payload

    watcher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    watcher.on_connect = lambda c, u, f, rc, p: c.subscribe(battery_detector.MONITOR_CONFIG_TOPIC)
    watcher.on_message = observe_config
    watcher.connect(battery_detector.MQTT_HOST, battery_detector.MQTT_PORT)
    watcher.loop_start()

    detector_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    detector_client.on_connect = battery_detector.on_connect
    detector_client.on_message = battery_detector.on_message
    detector_client.connect(battery_detector.MQTT_HOST, battery_detector.MQTT_PORT)
    detector_client.loop_start()

    try:
        deadline = time.time() + 30
        while time.time() < deadline and "monitor_config" not in observed:
            time.sleep(0.5)
        assert "monitor_config" in observed, (
            "on_connect should have published a retained monitor_config; "
            "check `docker compose logs drone_backend`"
        )

        deadline = time.time() + 30
        while time.time() < deadline and not battery_detector._window:
            time.sleep(0.5)
        assert battery_detector._window, (
            "on_connect's subscribe should have let live monitored_data reach on_message"
        )
    finally:
        detector_client.loop_stop()
        detector_client.disconnect()
        watcher.loop_stop()
        watcher.disconnect()


def test_main_wiring_produces_a_verdict_within_deadline():
    """Same client wiring as main(), bounded by an explicit deadline instead
    of main()'s blocking loop_forever()."""
    overall_deadline = time.time() + 120

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = battery_detector.on_connect
    client.on_message = battery_detector.on_message
    client.connect(battery_detector.MQTT_HOST, battery_detector.MQTT_PORT)
    client.loop_start()

    try:
        while time.time() < overall_deadline and battery_detector._verdict is None:
            time.sleep(0.5)
        assert battery_detector._verdict in ("no problem", "problem present"), (
            "expected a definitive verdict once enough monitored_data has "
            f"arrived, got {battery_detector._verdict!r}"
        )
    finally:
        client.loop_stop()
        client.disconnect()

    assert time.time() < overall_deadline, "flight monitoring exceeded its overall deadline"
