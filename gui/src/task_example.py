#!/usr/bin/env python3
"""Send a FlyWaypoints task to drone/Lime/task/new."""

import json
import time
import uuid

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT   = 1883
TOPIC  = "drone/Lime/task/new"

task = {
    "task_id": str(uuid.uuid4()),
    "states": [
        {
            "name": "FlyWaypoints",
            "args": {
                "waypoints": [
                    {
                        "latitude":  41.60634347171337,
                        "longitude": -86.35631690239772,
                        "altitude":  10,
                        "speed":     4.0,
                    },
                    {
                        "latitude":  41.606364598609595,
                        "longitude": -86.35568123272593,
                        "altitude":  10,
                        "speed":     4.0,
                    },
                ],
                "default_speed": 2.24,
            },
            "transitions": [
                {
                    "condition": "succeeded_waypoints",
                    "target":    "success",
                }
            ],
        }
    ],
}


def main() -> None:
    done = False

    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal done
        if rc != 0:
            print(f"Connection failed (rc={rc})")
            done = True
            return
        print(f"Connected to {BROKER}:{PORT}")
        payload = json.dumps(task)
        client.publish(TOPIC, payload, qos=1)
        print(f"Published → {TOPIC}")
        print(f"  task_id: {task['task_id']}")
        done = True

    client = mqtt.Client()
    client.on_connect = on_connect
    client.connect(BROKER, PORT, keepalive=30)
    client.loop_start()

    for _ in range(50):          # wait up to 5 s
        if done:
            break
        time.sleep(0.1)

    client.loop_stop()
    client.disconnect()
    print("Done.")


if __name__ == "__main__":
    main()
