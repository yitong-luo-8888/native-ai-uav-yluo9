"""ATC Controller - Simple version for 2 drones concurrent."""

import json
import math
import time
import paho.mqtt.client as mqtt

EARTH_RADIUS_M = 6378137.0

class ATCController:
    def __init__(self, min_separation_m):
        self.min_separation = min_separation_m
        self.action_threshold = min_separation_m * 1.5
        
        self.drones = {}
        self.home_positions = {}
        self.mission_status = {}
        self.interrupted = set()
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect("localhost", 1883)
        self.client.loop_start()
        
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe("uav/+/telemetry")
        client.subscribe("uav/+/home")
        
    def _on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) < 3:
            return
        drone_id = parts[1]
        topic_type = parts[2]
        
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
            
        if topic_type == "telemetry":
            self.drones[drone_id] = payload
        elif topic_type == "home":
            self.home_positions[drone_id] = payload
            
    def get_position(self, drone_id):
        if drone_id in self.drones:
            t = self.drones[drone_id]
            lat = t.get("lat")
            lon = t.get("lon")
            alt = t.get("alt_rel", 0)
            if lat is not None and lon is not None:
                return (lat, lon, alt)
        return None
        
    def distance_between(self, d1, d2):
        pos1 = self.get_position(d1)
        pos2 = self.get_position(d2)
        if not pos1 or not pos2:
            return float('inf')
        
        lat1, lon1, alt1 = pos1
        lat2, lon2, alt2 = pos2
        
        lat0_rad = math.radians((lat1 + lat2) / 2)
        dx = math.radians(lon2 - lon1) * math.cos(lat0_rad) * EARTH_RADIUS_M
        dy = math.radians(lat2 - lat1) * EARTH_RADIUS_M
        horizontal = math.hypot(dx, dy)
        vertical = abs(alt1 - alt2)
        return math.hypot(horizontal, vertical)
        
    def should_yield(self, drone_id, other_id):
        """Higher ID yields to lower ID."""
        return int(drone_id) > int(other_id)
        
    def send_command(self, drone_id, command):
        self.client.publish(f"uav/{drone_id}/command", json.dumps(command))
        
    def interrupt_drone(self, drone_id):
        if drone_id not in self.interrupted:
            self.send_command(drone_id, {"type": "interrupt"})
            self.interrupted.add(drone_id)
            self.mission_status[drone_id] = "waiting"
            print(f"    [ATC] UAV {drone_id} interrupted")
            
    def resume_drone(self, drone_id, waypoint):
        self.send_command(drone_id, {
            "type": "goto",
            "lat": waypoint["lat"],
            "lon": waypoint["lon"],
            "alt": waypoint["alt"]
        })
        self.interrupted.discard(drone_id)
        self.mission_status[drone_id] = "flying"
        print(f"    [ATC] UAV {drone_id} resumed")
        
    def distance_to_waypoint(self, drone_id, waypoint):
        pos = self.get_position(drone_id)
        if not pos:
            return float('inf')
        lat, lon, alt = pos
        
        lat0_rad = math.radians((lat + waypoint["lat"]) / 2)
        dx = math.radians(waypoint["lon"] - lon) * math.cos(lat0_rad) * EARTH_RADIUS_M
        dy = math.radians(waypoint["lat"] - lat) * EARTH_RADIUS_M
        horizontal = math.hypot(dx, dy)
        vertical = abs(alt - waypoint["alt"])
        return math.hypot(horizontal, vertical)