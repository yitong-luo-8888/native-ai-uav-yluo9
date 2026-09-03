#!/usr/bin/env python3
"""Zig-zag flight with altitude changes - HW01 Submission"""

import json
import math
import os
import sys
import time
import paho.mqtt.client as mqtt

VEHICLE_ID = os.environ.get("VEHICLE_ID", "1")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

HOME_TOPIC = f"uav/{VEHICLE_ID}/home"
TELEMETRY_TOPIC = f"uav/{VEHICLE_ID}/telemetry"
COMMAND_TOPIC = f"uav/{VEHICLE_ID}/command"

EARTH_RADIUS_M = 6378137.0
_latest = {}

def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(HOME_TOPIC)
    client.subscribe(TELEMETRY_TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
    except json.JSONDecodeError:
        return
    if msg.topic == HOME_TOPIC:
        _latest["home"] = payload
    elif msg.topic == TELEMETRY_TOPIC:
        _latest["telemetry"] = payload

def offset_to_lla(origin_lat, origin_lon, east_m, north_m):
    lat0_rad = math.radians(origin_lat)
    dlat = math.degrees(north_m / EARTH_RADIUS_M)
    dlon = math.degrees(east_m / (EARTH_RADIUS_M * math.cos(lat0_rad)))
    return origin_lat + dlat, origin_lon + dlon

def horizontal_distance_m(lat1, lon1, lat2, lon2):
    lat0_rad = math.radians((lat1 + lat2) / 2)
    dx = math.radians(lon2 - lon1) * math.cos(lat0_rad) * EARTH_RADIUS_M
    dy = math.radians(lat2 - lat1) * EARTH_RADIUS_M
    return math.hypot(dx, dy)

def wait_for(key, predicate, timeout, description):
    print(f"Waiting up to {timeout:.0f}s: {description}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = _latest.get(key)
        if value is not None and predicate(value):
            return value
        time.sleep(0.5)
    print(f"FAIL: timed out waiting for: {description}")
    sys.exit(1)

def execute_command(key, predicate, timeout, description, command, client):
    print(f"Waiting up to {timeout:.0f}s: {description}")
    deadline = time.time() + timeout
    next_send = 0.0
    while time.time() < deadline:
        if time.time() >= next_send:
            client.publish(COMMAND_TOPIC, json.dumps(command))
            print(f"  -> sent {command}")
            next_send = time.time() + 8.0
        value = _latest.get(key)
        if value is not None and predicate(value):
            return value
        time.sleep(0.5)
    print(f"FAIL: timed out waiting for: {description}")
    sys.exit(1)

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    home = wait_for("home", lambda h: True, 30, "retained home position")
    origin_lat, origin_lon = home["lat"], home["lon"]

    # Takeoff to 15m
    print(f"\n=== Takeoff to 15m ===")
    execute_command(
        "telemetry",
        lambda t: t.get("armed") and (t.get("alt_rel") or 0) > 13.5,
        60, "takeoff to 15m",
        {"type": "takeoff", "alt": 15.0}, client
    )
    print("  airborne at 15m")

    # Zig-zag pattern with altitude changes
    zigzag_points = [
        (5, 10, 15.0),    # (east, north, altitude)
        (-5, 20, 15.0),
        (5, 30, 25.0),    # Climb to 25m
        (-5, 40, 25.0),
        (5, 50, 10.0),    # Descend to 10m
    ]

    print("\n=== Flying zig-zag pattern ===")
    for i, (east, north, alt) in enumerate(zigzag_points):
        lat, lon = offset_to_lla(origin_lat, origin_lon, east, north)
        print(f"\n--- Waypoint {i+1}: {east}m east, {north}m north, {alt}m alt ---")
        execute_command(
            "telemetry",
            lambda t, lat=lat, lon=lon: (
                t.get("lat") is not None and
                horizontal_distance_m(t["lat"], t["lon"], lat, lon) < 3.0
            ),
            30, f"reach waypoint {i+1}",
            {"type": "goto", "lat": lat, "lon": lon, "alt": alt}, client
        )
        print(f"  reached waypoint {i+1}")

    # Return to home
    print("\n=== Returning home ===")
    execute_command(
        "telemetry",
        lambda t: (
            t.get("lat") is not None and
            horizontal_distance_m(t["lat"], t["lon"], origin_lat, origin_lon) < 3.0
        ),
        60, "return to home",
        {"type": "goto", "lat": origin_lat, "lon": origin_lon, "alt": 10.0}, client
    )
    print("  back at home")

    # Land
    print("\n=== Landing ===")
    execute_command(
        "telemetry",
        lambda t: not t.get("armed"),
        60, "land",
        {"type": "land"}, client
    )
    print("  landed successfully")

    print("\nPASS: Zig-zag mission complete!")
    client.loop_stop()

if __name__ == "__main__":
    main()
