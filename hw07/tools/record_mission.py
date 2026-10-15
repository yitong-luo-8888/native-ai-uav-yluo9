#!/usr/bin/env python3
"""record_mission.py -- log the MQTT traffic of an HW7 run, for report.md evidence.

Writes one timestamped line per mission/# message (mission/clues shortened
to its assessment_id, object, relevance, decision and search_center) plus
uav/<id>/telemetry once every 5 s.

    python hw07/tools/record_mission.py hw07/evidence/e2e/topics.log [--uav 1]
"""
import argparse
import json
import os
import time

import paho.mqtt.client as mqtt

KEYS = ("lat", "lon", "alt_rel", "activity", "battery_level")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out")
    parser.add_argument("--uav", default="1")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    args = parser.parse_args()
    telemetry = f"uav/{args.uav}/telemetry"
    out = open(args.out, "a", buffering=1)
    last = [0.0]

    def on_message(client, userdata, msg):
        now = time.strftime("%H:%M:%S")
        if msg.topic == telemetry:
            if time.time() - last[0] < 5:
                return
            last[0] = time.time()
            t = json.loads(msg.payload)
            out.write(f"{now} {msg.topic} " + " ".join(f"{k}={t.get(k)}" for k in KEYS) + "\n")
            return
        text = msg.payload.decode(errors="replace")
        if msg.topic == "mission/clues":
            a = json.loads(text)
            text = json.dumps({"assessment_id": a.get("assessment_id"),
                               "candidate": (a.get("candidate") or {}).get("candidate_id"),
                               "object": (a.get("descriptions") or [{}])[-1].get("object_type"),
                               "relevance": (a.get("relevance") or {}).get("relevance"),
                               "decision": a.get("decision"), "search_center": a.get("search_center")})
        out.write(f"{now} {msg.topic} {text[:800]}\n")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = lambda c, *a: (c.subscribe("mission/#", qos=1), c.subscribe(telemetry))
    client.on_message = on_message
    client.connect(args.host, 1883)
    client.loop_forever()


if __name__ == "__main__":
    main()
