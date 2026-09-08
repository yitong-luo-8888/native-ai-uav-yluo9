"""Multi-UAV GUI tracker - FIXED to close properly."""
import paho.mqtt.client as mqtt
import json
import math
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from collections import deque
import time

EARTH_RADIUS_M = 6378137.0
positions = {}
trails = {}
home = None
running = True

COLORS = {'1': 'red', '2': 'blue', '3': 'green', '4': 'orange', '5': 'purple'}

def lla_to_enu(lat, lon, origin_lat, origin_lon):
    lat0_rad = math.radians(origin_lat)
    x_east = math.radians(lon - origin_lon) * math.cos(lat0_rad) * EARTH_RADIUS_M
    y_north = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    return x_east, y_north

def on_close(event):
    """Handle window close event."""
    global running
    running = False
    print("\nWindow closed, shutting down...")

def on_message(client, userdata, msg):
    global home
    parts = msg.topic.split("/")
    if len(parts) < 3:
        return
    
    drone_id = parts[1]
    topic_type = parts[2]
    
    try:
        payload = json.loads(msg.payload)
    except:
        return
    
    if topic_type == "home":
        home = (payload["lat"], payload["lon"])
        print(f"Home: {home}")
    elif topic_type == "telemetry" and home:
        if payload.get("lat") and payload.get("lon"):
            x, y = lla_to_enu(payload["lat"], payload["lon"], home[0], home[1])
            positions[drone_id] = (x, y, payload.get("alt_rel", 0))
            
            if drone_id not in trails:
                trails[drone_id] = deque(maxlen=100)
            trails[drone_id].append((x, y))

# Setup MQTT
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message
client.connect("localhost", 1883)
client.subscribe("uav/+/telemetry")
client.subscribe("uav/+/home")
client.loop_start()

print("Waiting for data...")
time.sleep(2)

# Setup plot
plt.ion()
fig = plt.figure(figsize=(10, 8))
fig.canvas.mpl_connect('close_event', on_close)  # This makes X button work!

print("GUI Tracker running!")
print("Press Ctrl+C or click X to close")

try:
    while running:
        if not plt.fignum_exists(fig.number):
            break
            
        plt.clf()
        ax = plt.gca()
        ax.set_xlabel("East (m)")
        ax.set_ylabel("North (m)")
        ax.set_title("Multi-UAV Tracker")
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)
        
        ax.set_xlim(-100, 100)
        ax.set_ylim(-100, 100)
        
        # Home marker
        ax.scatter(0, 0, c='black', s=150, marker='s', label='Home', zorder=3)
        
        # Trails
        for drone_id, trail in trails.items():
            if len(trail) > 1:
                xs = [p[0] for p in trail]
                ys = [p[1] for p in trail]
                color = COLORS.get(drone_id, 'black')
                ax.plot(xs, ys, '-', color=color, alpha=0.5, linewidth=2)
        
        # Drones
        for drone_id, (x, y, alt) in sorted(positions.items()):
            color = COLORS.get(drone_id, 'black')
            ax.scatter(x, y, c=color, s=300, marker='^',
                      label=f'UAV {drone_id} ({alt:.1f}m)', zorder=5)
            ax.annotate(f'UAV {drone_id}',
                       (x, y), xytext=(10, 15), textcoords='offset points',
                       fontsize=12, fontweight='bold', color=color)
        
        ax.legend(loc='upper right', fontsize=10)
        
        # Distance info
        drone_ids = sorted(positions.keys())
        if len(drone_ids) >= 2:
            info = []
            for i in range(len(drone_ids)):
                for j in range(i+1, len(drone_ids)):
                    d1, d2 = drone_ids[i], drone_ids[j]
                    p1, p2 = positions[d1], positions[d2]
                    dist = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
                    info.append(f"{d1}-{d2}: {dist:.1f}m")
            ax.text(0.02, 0.02, " | ".join(info),
                   transform=ax.transAxes, fontsize=9,
                   bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))
        
        plt.pause(0.2)
        
except KeyboardInterrupt:
    print("\nCtrl+C pressed, stopping...")
finally:
    print("Cleaning up...")
    client.loop_stop()
    plt.close('all')
    print("Done!")
