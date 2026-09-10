#!/usr/bin/env python3
import json
import threading
from typing import Callable, Dict, Any, Optional

import paho.mqtt.client as mqtt


class DroneMqttClient:
    """
    Generic MQTT client that listens for DroneResponse status messages
    and calls a callback with parsed state.

    on_state callback signature:
        (uavid: str,
         location: Dict[str, Any],
         drone_attitude: Dict[str, Any],
         drone_heading: float,
         state_info: Dict[str, Any]) -> None
    """

    def __init__(
        self,
        broker: str = "localhost",
        port: int = 1883,
        topic: str = "update_drone",
        on_state: Optional[
            Callable[[str, Dict[str, Any], Dict[str, Any], float, Dict[str, Any]], None]
        ] = None,
        on_connect: Optional[Callable[[], None]] = None,
    ):
        self.broker = broker
        self.port = port
        self.topic = topic

        self.on_state                = on_state
        self.on_connect              = on_connect

        self._client: Optional[mqtt.Client] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        client = mqtt.Client()
        self._client = client

        def on_connect(client, userdata, flags, rc, properties=None):
            print("MQTT connected with rc =", rc)

            # Main status topic (drone state)
            client.subscribe(self.topic, qos=0)
            print(f"Subscribed to topic: {self.topic}")

            if self.on_connect:
                self.on_connect()

        def on_message(client, userdata, msg):
            try:
                # --- Normal drone status topic ---
                if msg.topic != self.topic:
                    # Unknown/unhandled topic; just log
                    print(f"[MQTT] Unhandled topic {msg.topic}: {msg.payload!r}")
                    return

                payload = msg.payload.decode("utf-8", errors="ignore")
                data = json.loads(payload)

                uavid = data.get("uavid") or data.get("uavID") or "Unknown"
                status = data.get("status", {}) or {}
                location = status.get("location", {}) or {}
                drone_attitude = status.get("drone_attitude", {}) or {}
                drone_heading = status.get("drone_heading", None)
                battery = status.get("battery", {}) or {}

                lat = location.get("latitude")
                lon = location.get("longitude")
                alt = location.get("altitude")

                ax = drone_attitude.get("x")
                ay = drone_attitude.get("y")
                az = drone_attitude.get("z")
                aw = drone_attitude.get("w")

                state_info = {
                    "status":           status.get("status", ""),
                    "mode":             status.get("mode", ""),
                    "onboard_pilot":    status.get("onboard_pilot", ""),
                    "air_lease_state":  status.get("air_lease_state", ""),
                    "heartbeat_status": status.get("heartbeat_status", ""),
                    "state_type":       status.get("state_type", ""),
                    "speed":            status.get("speed", None),
                    "armed":            status.get("armed", None),
                    "geofence":         status.get("geofence", None),
                    "voltage":          battery.get("voltage", None),
                    "battery_level":    battery.get("level", None),   # 0.0–1.0
                    "battery_current":  battery.get("current", None),
                }

                if self.on_state is not None:
                    self.on_state(
                        uavid,
                        location,
                        drone_attitude,
                        float(drone_heading) if drone_heading is not None else 0.0,
                        state_info,
                    )

            except Exception as ex:
                print("MQTT parse error:", ex)
                print("  Raw payload:", repr(msg.payload))

        client.on_connect = on_connect
        client.on_message = on_message

        def loop():
            try:
                client.connect(self.broker, self.port, keepalive=30)
                client.loop_forever(retry_first_connection=True)
            except Exception as ex:
                print("MQTT loop exception:", ex)

        t = threading.Thread(target=loop, name="mqtt-loop", daemon=True)
        self._thread = t
        t.start()

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        """
        Convenience wrapper to publish MQTT messages through the same client.

        payload should be a string (JSON, etc.) – encoding is handled by paho.
        """
        if self._client is None:
            print("[DroneMqttClient] publish called but client is None")
            return
        try:
            info = self._client.publish(topic, payload, qos=qos, retain=retain)
            # You can call info.wait_for_publish() from the caller if you need blocking.
        except Exception as ex:
            print("[DroneMqttClient] publish error:", ex)

    def stop(self) -> None:
        try:
            if self._client is not None:
                self._client.loop_stop()
                self._client.disconnect()
        except Exception:
            pass
