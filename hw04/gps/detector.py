"""Step 4 GPS detector.

Watches `gps.satellites_visible` on uav/<id>/monitored_data and prints one
of three verdicts continuously: "problem present", "no problem",
"not enough data yet".

Threshold reasoning (see REPORT.md):
  - Normal flight: satellites_visible is constant at 10 (SITL GPS is
    deterministic; observed across a full test_monitor_flight.py run).
  - Low severity drops it to 7-9, Medium 5-7, High 2-4 (mischief_maker.py's
    calibrated catalog; observed Low->7, Medium->7, High->2 live).
  - There is no natural gap between normal and Low, so the threshold is
    "< 10" -- anything below the known-normal value for a sustained window.
  - Window is short (4s, ~8 samples at telemetry rate) because the signal
    is deterministic: a real fault changes it on the next telemetry tick,
    and a short window is enough to avoid reacting to a single odd sample.
"""
import json
import os
from collections import deque

import paho.mqtt.client as mqtt

VEHICLE_ID = os.environ.get("VEHICLE_ID", "1")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

MONITOR_CONFIG_TOPIC = f"uav/{VEHICLE_ID}/monitor_config"
MONITORED_DATA_TOPIC = f"uav/{VEHICLE_ID}/monitored_data"

CATEGORIES = ["gps"]

WINDOW_S = 4.0
MIN_SAMPLES = 4          # ~2 telemetry ticks/sec; 4 samples ~= 2s of data
NORMAL_SATS = 10         # observed baseline during normal flight
PROBLEM_BELOW = NORMAL_SATS  # anything below 10 is suspect


class GpsDetector:
    def __init__(self):
        self.samples = deque()  # (t, sats)

    def on_sample(self, payload):
        now = payload.get("timestamp")
        gps = payload.get("gps")
        if now is None or not gps:
            return
        sats = gps.get("satellites_visible")
        if sats is None:
            return

        self.samples.append((now, sats))
        cutoff = now - WINDOW_S
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

        self.report()

    def report(self):
        span = self.samples[-1][0] - self.samples[0][0]
        if len(self.samples) < MIN_SAMPLES or span < WINDOW_S * 0.5:
            print(f"not enough data yet ({len(self.samples)} samples over {span:.1f}s)")
            return

        values = [v for _, v in self.samples]
        lo = min(values)
        hi = max(values)
        latest = values[-1]
        mean = sum(values) / len(values)

        if lo < PROBLEM_BELOW:
            print(
                f"problem present -- satellites_visible fell to {lo} "
                f"(window {WINDOW_S:.0f}s: min={lo}, max={hi}, mean={mean:.1f}; "
                f"normal is {NORMAL_SATS})"
            )
        else:
            print(
                f"no problem -- satellites_visible steady at {latest} "
                f"(window {WINDOW_S:.0f}s: min={lo}, max={hi}, mean={mean:.1f})"
            )


def main():
    detector = GpsDetector()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"Connected to {MQTT_HOST}:{MQTT_PORT} ({reason_code})")
        client.publish(
            MONITOR_CONFIG_TOPIC,
            json.dumps({"categories": CATEGORIES}),
            retain=True,
        )
        client.subscribe(MONITORED_DATA_TOPIC)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        detector.on_sample(payload)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT)
    print(
        f"GPS detector running (window {WINDOW_S}s, threshold < {PROBLEM_BELOW}). "
        f"Ctrl-C to stop."
    )
    client.loop_forever()


if __name__ == "__main__":
    main()