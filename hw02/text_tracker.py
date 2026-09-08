"""Text-based multi-UAV tracker - prints positions in real-time."""
import paho.mqtt.client as mqtt
import json
import math
import time
import os

EARTH_RADIUS_M = 6378137.0

positions = {}
home = None

def lla_to_enu(lat, lon, origin_lat, origin_lon):
    lat0_rad = math.radians(origin_lat)
    x_east = math.radians(lon - origin_lon) * math.cos(lat0_rad) * EARTH_RADIUS_M
    y_north = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    return x_east, y_north

def on_message(client, userdata, msg):
    global home
    parts = msg.topic.split("/")
    drone_id = parts[1]
    topic_type = parts[2]
    
    try:
        payload = json.loads(msg.payload)
    except:
        return
    
    if topic_type == "home":
        home = (payload["lat"], payload["lon"])
    elif topic_type == "telemetry":
        if payload.get("lat") and payload.get("lon") and home:
            x, y = lla_to_enu(payload["lat"], payload["lon"], home[0], home[1])
            positions[drone_id] = {
                'east': x,
                'north': y,
                'alt': payload.get("alt_rel", 0),
                'mode': payload.get("mode", "?"),
                'armed': payload.get("armed", False)
            }

def display():
    """Clear screen and show all drone positions."""
    os.system('clear')  # Clear terminal
    
    print("=" * 70)
    print("                MULTI-UAV REAL-TIME TRACKER")
    print("=" * 70)
    print(f"{'UAV':<5} {'East(m)':>10} {'North(m)':>10} {'Alt(m)':>8} {'Mode':>12} {'Armed':>6}")
    print("-" * 70)
    
    for drone_id in sorted(positions.keys()):
        p = positions[drone_id]
        print(f"{drone_id:<5} {p['east']:>10.1f} {p['north']:>10.1f} {p['alt']:>8.1f} {p['mode']:>12} {str(p['armed']):>6}")
    
    print("-" * 70)
    
    # Show distances between drones
    drone_ids = sorted(positions.keys())
    if len(drone_ids) >= 2:
        print("\nDistances:")
        for i in range(len(drone_ids)):
            for j in range(i+1, len(drone_ids)):
                d1, d2 = drone_ids[i], drone_ids[j]
                p1, p2 = positions[d1], positions[d2]
                dist = math.hypot(p1['east'] - p2['east'], p1['north'] - p2['north'])
                print(f"  UAV {d1} <-> UAV {d2}: {dist:.1f}m")
    
    print("\nPress Ctrl+C to stop")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message
client.connect("localhost", 1883)
client.subscribe("uav/+/telemetry")
client.subscribe("uav/+/home")
client.loop_start()

print("Waiting for telemetry...")
time.sleep(3)

try:
    while True:
        display()
        time.sleep(1)  # Update every second
except KeyboardInterrupt:
    print("\nStopping tracker...")
    client.loop_stop()
