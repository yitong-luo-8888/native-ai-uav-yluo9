"""Unit tests for lab/lesson4/battery/battery_detector.py.

`evaluate` is the windowed threshold logic and is treated as PURE: it takes
`now` as an argument and reads the module-level `_window` deque, which
these tests populate directly before calling it -- the same idea as
injecting state into a pure function, just via module state instead of a
parameter, since `evaluate()` has no other way to receive a window.

`on_message` is STUB: it mutates the module-level `_window` / `_verdict`
state from a parsed MQTT message; tests drive it with a fake message object
(see conftest.py's FakeMqttMessage) instead of a real MQTT client.

`on_connect` and `main` are LIVE (a real client publish/subscribe and a
blocking `loop_forever()`, respectively) and are covered only by
generated-tests/integration/test_battery_detector_live.py.
"""
import json

import pytest

import lab.lesson4.battery.battery_detector as battery_detector
from conftest import FakeMqttMessage


# ---------------------------------------------------------------------------
# PURE (per this skill's worked example for this file): evaluate
# ---------------------------------------------------------------------------

def test_evaluate_empty_window_reports_not_enough_data():
    verdict, evidence = battery_detector.evaluate(now=0.0)
    assert verdict == "not enough data yet"
    assert "0 sample" in evidence


def test_evaluate_too_few_samples_reports_not_enough_data():
    for t in (0.0, 1.0, 2.0):
        battery_detector._window.append((t, {"voltage_v": 12.6}))
    verdict, evidence = battery_detector.evaluate(now=10.0)
    assert verdict == "not enough data yet"
    assert "3 sample" in evidence


def test_evaluate_window_span_too_short_reports_not_enough_data():
    # 5 samples (meets MIN_SAMPLES) but they only span 0.5s, well under
    # WINDOW_S * 0.9 == 4.5s.
    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
        battery_detector._window.append((t, {"voltage_v": 12.6}))
    verdict, evidence = battery_detector.evaluate(now=1.0)
    assert verdict == "not enough data yet"
    assert "5 sample" in evidence


def test_evaluate_missing_voltage_readings_reports_not_enough_data():
    for t in (5.0, 6.0, 7.0, 8.0, 9.0):
        battery_detector._window.append((t, {"current_a": 5.0}))  # no voltage_v
    verdict, evidence = battery_detector.evaluate(now=10.0)
    assert verdict == "not enough data yet"
    assert "no voltage readings" in evidence


def test_evaluate_below_threshold_reports_problem_present():
    for t in (0.0, 1.0, 2.0, 3.0, 4.5):
        battery_detector._window.append(
            (t, {"voltage_v": 10.5, "current_a": 8.0, "remaining_pct": 15})
        )
    verdict, evidence = battery_detector.evaluate(now=4.5)
    assert verdict == "problem present"
    assert "10.50V" in evidence
    assert "current draw 8.0A" in evidence
    assert "remaining 15%" in evidence


def test_evaluate_above_threshold_reports_no_problem():
    for t in (0.0, 1.0, 2.0, 3.0, 4.5):
        battery_detector._window.append((t, {"voltage_v": 12.6}))
    verdict, evidence = battery_detector.evaluate(now=4.5)
    assert verdict == "no problem"
    assert "12.60V" in evidence


def test_evaluate_exactly_at_threshold_reports_no_problem():
    # avg_voltage < WARN_VOLTAGE is a strict inequality, so sitting exactly
    # on WARN_VOLTAGE (11.0V) must not read as a problem.
    for t in (0.0, 1.0, 2.0, 3.0, 4.5):
        battery_detector._window.append((t, {"voltage_v": battery_detector.WARN_VOLTAGE}))
    verdict, _ = battery_detector.evaluate(now=4.5)
    assert verdict == "no problem"


def test_evaluate_single_low_sample_amid_normal_readings_does_not_trigger_problem():
    # Negative test: the monitor is windowed, not single-point (see module
    # docstring) -- one noisy low reading among otherwise-normal samples
    # must not flip the verdict on its own.
    readings = [12.6, 12.6, 9.0, 12.6, 12.6]
    for t, voltage in zip((0.0, 1.0, 2.0, 3.0, 4.5), readings):
        battery_detector._window.append((t, {"voltage_v": voltage}))
    verdict, evidence = battery_detector.evaluate(now=4.5)
    assert verdict == "no problem"
    assert "min 9.00V" in evidence


def test_evaluate_averages_only_over_present_voltage_readings():
    # Edge case: some samples in the window are missing voltage_v entirely
    # (e.g. a partial telemetry payload). The average must be computed only
    # from the samples that actually have a reading.
    battery_detector._window.append((0.0, {"current_a": 5.0}))  # no voltage_v
    battery_detector._window.append((1.0, {"voltage_v": 10.0}))
    battery_detector._window.append((2.0, {"current_a": 5.0}))  # no voltage_v
    battery_detector._window.append((3.0, {"voltage_v": 10.0}))
    battery_detector._window.append((4.5, {"voltage_v": 10.0}))

    verdict, evidence = battery_detector.evaluate(now=4.5)
    assert verdict == "problem present"
    assert "10.00V" in evidence


# ---------------------------------------------------------------------------
# STUB: on_message
# ---------------------------------------------------------------------------

def test_on_message_appends_battery_reading_to_window():
    payload = {"battery": {"voltage_v": 12.6, "current_a": 5.0, "remaining_pct": 80}, "timestamp": 100.0}
    msg = FakeMqttMessage(json.dumps(payload).encode())
    battery_detector.on_message(client=None, userdata=None, msg=msg)
    assert list(battery_detector._window) == [
        (100.0, {"voltage_v": 12.6, "current_a": 5.0, "remaining_pct": 80})
    ]


def test_on_message_ignores_malformed_json_payload():
    battery_detector._window.append((1.0, {"voltage_v": 12.6}))
    msg = FakeMqttMessage(b"{not valid json")
    battery_detector.on_message(client=None, userdata=None, msg=msg)
    assert list(battery_detector._window) == [(1.0, {"voltage_v": 12.6})]


def test_on_message_ignores_payload_missing_battery_key():
    msg = FakeMqttMessage(json.dumps({"foo": "bar"}).encode())
    battery_detector.on_message(client=None, userdata=None, msg=msg)
    assert list(battery_detector._window) == []


def test_on_message_trims_samples_older_than_window():
    battery_detector._window.append((0.0, {"voltage_v": 12.6}))
    payload = {"battery": {"voltage_v": 12.5}, "timestamp": 10.0}  # 10.0 - 0.0 > WINDOW_S
    msg = FakeMqttMessage(json.dumps(payload).encode())
    battery_detector.on_message(client=None, userdata=None, msg=msg)
    assert list(battery_detector._window) == [(10.0, {"voltage_v": 12.5})]


def test_on_message_sets_module_verdict_from_evaluate():
    for t in (0.0, 1.0, 2.0, 3.0):
        battery_detector._window.append((t, {"voltage_v": 12.6}))
    payload = {"battery": {"voltage_v": 12.6}, "timestamp": 4.5}
    msg = FakeMqttMessage(json.dumps(payload).encode())
    battery_detector.on_message(client=None, userdata=None, msg=msg)
    assert battery_detector._verdict == "no problem"


def test_on_message_defaults_timestamp_to_now_when_missing(monkeypatch):
    monkeypatch.setattr(battery_detector.time, "time", lambda: 42.0)
    payload = {"battery": {"voltage_v": 12.6}}  # no "timestamp" key
    msg = FakeMqttMessage(json.dumps(payload).encode())
    battery_detector.on_message(client=None, userdata=None, msg=msg)
    assert battery_detector._window[-1][0] == 42.0
