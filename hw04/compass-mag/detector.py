"""Step 4 compass detector.

Watches `compass.field_magnitude` on uav/<id>/monitored_data and prints one
of three verdicts continuously: "problem present", "no problem",
"not enough data yet".

Why spread and not level: during normal flight |B| sits steady around
525-530 (a small wobble, observed spread ~10 over a whole flight). Under a
mag fault, SIM_MAG_RND makes the reading noisy around that same value --
Medium (SIM_MAG_RND ~217) swings ~425-600, High (~700) swings ~400-800.
The fault straddles the normal value on BOTH sides, so "value below X" is
the wrong rule. What changes is the range: normal spread stays tiny, faulty
spread is large. So this detector measures max-min over a rolling window.

Threshold reasoning (see REPORT.md):
  - Normal: |B| steady ~525-530; whole-flight spread observed to be small.
  - Low  (SIM_MAG_RND  50-150): ~500-550, spread ~50  (observed)
  - Med  (SIM_MAG_RND 150-400): ~425-600, spread ~175 (observed)
  - High (SIM_MAG_RND 400-800): ~400-800, spread ~400 (observed)
  - SPREAD_THRESHOLD=30 sits above normal wobble and below Low's spread,
    with margin on both sides.
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

CATEGORIES = ["compass"]

WINDOW_S = 5.0
MIN_SAMPLES = 8            # ~2 ticks/sec; 8 ~= 4s of data
SPREAD_THRESHOLD = 30.0    # |B| spread over the window above which it's a fault


class CompassDetector:
    def __init__(self):
        self.samples = deque()  # (t, |B|)

    def on_sample(self, payload):
        now = payload.get("timestamp")
        comp = payload.get("compass")
        if now is None or not comp:
            return
        b = comp.get("field_magnitude")
        if b is None:
            return

        self.samples.append((now, b))
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
        lo, hi = min(values), max(values)
        spread = hi - lo

        if spread > SPREAD_THRESHOLD:
            print(
                f"problem present -- |B| spread {spread:.0f} over last "
                f"{span:.1f}s (min={lo:.0f} max={hi:.0f}; "
                f"threshold {SPREAD_THRESHOLD:.0f}, normal spread ~10)"
            )
        else:
            print(
                f"no problem -- |B| spread {spread:.0f} over last {span:.1f}s "
                f"(min={lo:.0f} max={hi:.0f})"
            )


def main():
    detector = CompassDetector()
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
        f"Compass detector running (window {WINDOW_S}s, "
        f"spread threshold > {SPREAD_THRESHOLD}). Ctrl-C to stop."
    )
    client.loop_forever()


if __name__ == "__main__":
    main()