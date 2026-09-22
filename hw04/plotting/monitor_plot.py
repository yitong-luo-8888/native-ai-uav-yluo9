"""Step 2 plotter: subscribe to GPS + compass, plot them live.

Extends the Step 1 subscriber with a rolling history and matplotlib redraw.
Follows the battery example's pattern: deque-based history trimmed to a time
window, redrawn on a plt.show(block=False) + plt.pause loop (not FuncAnimation,
which the guide says was unreliable on this project's WSL2/Tk setup).

Signals plotted:
  GPS row      -> satellites_visible (left axis), hdop_h + h_acc_m (right axis)
  Compass row  -> mag_x, mag_y, mag_z, field_magnitude
"""
import json
import os
import time
from collections import deque

import matplotlib.pyplot as plt
import paho.mqtt.client as mqtt

VEHICLE_ID = os.environ.get("VEHICLE_ID", "1")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

MONITOR_CONFIG_TOPIC = f"uav/{VEHICLE_ID}/monitor_config"
MONITORED_DATA_TOPIC = f"uav/{VEHICLE_ID}/monitored_data"

CATEGORIES = ["gps", "compass"]

HISTORY_S = 60
PLOT_REFRESH_S = 0.2

GPS_FIELDS = ["satellites_visible", "hdop_h", "h_acc_m"]
COMPASS_FIELDS = ["mag_x", "mag_y", "mag_z", "field_magnitude"]


class MonitorClient:
    """Same wiring as Step 1: publish monitor_config (retained), subscribe to
    monitored_data, hand each parsed payload to on_sample."""

    def __init__(self, on_sample, categories=CATEGORIES):
        self.on_sample = on_sample
        self.categories = list(categories)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"Connected to {MQTT_HOST}:{MQTT_PORT} ({reason_code})")
        client.publish(
            MONITOR_CONFIG_TOPIC,
            json.dumps({"categories": self.categories}),
            retain=True,
        )
        client.subscribe(MONITORED_DATA_TOPIC)
        print(f"Requested categories: {self.categories}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        self.on_sample(payload)

    def run(self):
        self.client.connect(MQTT_HOST, MQTT_PORT)
        self.client.loop_start()  # background thread; main thread drives the plot


def trim(hist):
    """Drop samples older than HISTORY_S from every deque in `hist`.

    hist is {category: {field: deque of (t, value)}} -- two levels.
    """
    cutoff = time.time() - HISTORY_S
    for fields in hist.values():
        for series in fields.values():
            while series and series[0][0] < cutoff:
                series.popleft()


def main():
    hist = {}
    for cat, fields in (("gps", GPS_FIELDS), ("compass", COMPASS_FIELDS)):
        hist[cat] = {name: deque() for name in fields}

    def on_sample(payload):
        t = payload.get("timestamp")
        if t is None:
            return
        for cat in ("gps", "compass"):
            block = payload.get(cat)
            if not block:
                continue
            for name in hist[cat]:
                if name in block:
                    hist[cat][name].append((t, block[name]))
        trim(hist)

    client = MonitorClient(on_sample)
    client.run()

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    gps_axes = axes[0].twinx()

    (gps_sats_line,) = axes[0].plot([], [], label="satellites_visible", color="tab:blue")
    axes[0].set_ylabel("sats", color="tab:blue")
    (gps_hdop_line,) = gps_axes.plot([], [], label="hdop_h", color="tab:orange")
    (gps_hacc_line,) = gps_axes.plot([], [], label="h_acc_m", color="tab:green")
    gps_axes.set_ylabel("hdop_h / h_acc_m")
    axes[0].set_title("GPS")
    axes[0].legend(loc="upper left", fontsize=8)
    gps_axes.legend(loc="upper right", fontsize=8)

    compass_lines = {}
    colors = ["tab:red", "tab:purple", "tab:brown", "tab:pink"]
    for name, color in zip(COMPASS_FIELDS, colors):
        (line,) = axes[1].plot([], [], label=name, color=color)
        compass_lines[name] = line
    axes[1].set_title("Compass")
    axes[1].set_ylabel("raw mag")
    axes[1].set_xlabel("time (s, relative to plot start)")
    axes[1].legend(loc="upper left", fontsize=8)

    t0 = time.time()

    plt.ion()
    plt.show(block=False)

    print("Plotting. Ctrl-C to stop.")
    try:
        while True:
            # Each line's x and y come from the same deque, so they're always
            # the same length -- no need for a separate shared `times` deque.
            def draw(line, series):
                if not series:
                    return
                xs = [t - t0 for t, _ in series]
                ys = [v for _, v in series]
                line.set_data(xs, ys)

            draw(gps_sats_line, hist["gps"]["satellites_visible"])
            draw(gps_hdop_line, hist["gps"]["hdop_h"])
            draw(gps_hacc_line, hist["gps"]["h_acc_m"])
            for name, line in compass_lines.items():
                draw(line, hist["compass"][name])

            for ax in (axes[0], gps_axes, axes[1]):
                ax.relim()
                ax.autoscale_view()

            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            plt.pause(PLOT_REFRESH_S)
    except KeyboardInterrupt:
        pass
    finally:
        client.client.loop_stop()
        client.client.disconnect()
        plt.close(fig)


if __name__ == "__main__":
    main()