"""Centralized ATC with velocity-based conflict prediction."""

import json
import math
import time
import paho.mqtt.client as mqtt

EARTH_RADIUS_M = 6378137.0

class ATCController:
    def __init__(self, min_separation_m):
        self.min_separation = min_separation_m
        self.action_threshold = min_separation_m + 10
        self.crash_threshold = min_separation_m
        self.lookahead_time = 5.0  # Predict 5 seconds into future
        
        self.drones = {}
        self.home_positions = {}
        self.mission_status = {}
        self.interrupted = set()
        self.interrupt_time = {}
        self.interrupt_count = {}
        self.current_altitude = {}
        self.prev_positions = {}  # Track previous positions for velocity
        self.prev_time = {}       # Track when we last saw each drone
        
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
            # Track previous position for velocity calculation
            current_pos = self.get_position(drone_id)
            if current_pos:
                self.prev_positions[drone_id] = current_pos
                self.prev_time[drone_id] = time.time()
            
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
        
    def get_velocity(self, drone_id):
        """Calculate velocity vector from telemetry or position changes."""
        # First try to use telemetry groundspeed and heading
        if drone_id in self.drones:
            t = self.drones[drone_id]
            groundspeed = t.get("groundspeed", 0)
            heading = t.get("heading", 0)
            
            if groundspeed and groundspeed > 0.5:  # Moving
                # Convert heading (degrees) and speed to velocity vector
                heading_rad = math.radians(heading)
                # East component
                v_east = groundspeed * math.sin(heading_rad)
                # North component
                v_north = groundspeed * math.cos(heading_rad)
                return (v_east, v_north)
        
        # Fallback: calculate from position changes
        if drone_id in self.prev_positions:
            prev_pos = self.prev_positions[drone_id]
            curr_pos = self.get_position(drone_id)
            if prev_pos and curr_pos:
                dt = time.time() - self.prev_time.get(drone_id, time.time())
                if dt > 0.1:  # At least 100ms between updates
                    # Calculate velocity in m/s
                    lat0_rad = math.radians(curr_pos[0])
                    v_east = math.radians(curr_pos[1] - prev_pos[1]) * math.cos(lat0_rad) * EARTH_RADIUS_M / dt
                    v_north = math.radians(curr_pos[0] - prev_pos[0]) * EARTH_RADIUS_M / dt
                    return (v_east, v_north)
        
        return (0, 0)
        
    def get_predicted_position(self, drone_id, time_ahead):
        """Predict where drone will be in time_ahead seconds."""
        pos = self.get_position(drone_id)
        if not pos:
            return None
        
        lat, lon, alt = pos
        v_east, v_north = self.get_velocity(drone_id)
        
        # Convert velocity to lat/lon changes
        lat0_rad = math.radians(lat)
        d_lat = (v_north * time_ahead) / EARTH_RADIUS_M
        d_lon = (v_east * time_ahead) / (EARTH_RADIUS_M * math.cos(lat0_rad))
        
        # Predict future position
        future_lat = lat + math.degrees(d_lat)
        future_lon = lon + math.degrees(d_lon)
        
        return (future_lat, future_lon, alt)
        
    def predicted_distance_between(self, d1, d2, time_ahead):
        """Calculate predicted distance between two drones in time_ahead seconds."""
        pos1 = self.get_predicted_position(d1, time_ahead)
        pos2 = self.get_predicted_position(d2, time_ahead)
        
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
        
    def distance_between(self, d1, d2):
        """Current 3D distance between two drones."""
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
        
    def find_conflicts(self):
        """Find conflicts using predicted positions."""
        conflicts = []
        drone_ids = list(self.drones.keys())
        
        for i in range(len(drone_ids)):
            for j in range(i+1, len(drone_ids)):
                d1, d2 = drone_ids[i], drone_ids[j]
                
                # Check current distance
                current_dist = self.distance_between(d1, d2)
                
                # Check predicted distance in 3 seconds
                predicted_dist = self.predicted_distance_between(d1, d2, 3.0)
                
                # Check predicted distance in 5 seconds
                predicted_dist_5s = self.predicted_distance_between(d1, d2, 5.0)
                
                # Conflict if predicted to get too close
                if predicted_dist < self.action_threshold or predicted_dist_5s < self.min_separation:
                    conflicts.append((d1, d2, current_dist, predicted_dist))
                    
        return conflicts
        
    def check_crash(self):
        """CRASH if any drones are currently within min_separation."""
        drone_ids = list(self.drones.keys())
        for i in range(len(drone_ids)):
            for j in range(i+1, len(drone_ids)):
                d1, d2 = drone_ids[i], drone_ids[j]
                dist = self.distance_between(d1, d2)
                if dist < self.min_separation:
                    return True, d1, d2, dist
        return False, None, None, None
        
    def detect_deadlock(self):
        """Detect if two interrupted drones are waiting on each other."""
        interrupted_list = list(self.interrupted)
        if len(interrupted_list) < 2:
            return None
            
        for i in range(len(interrupted_list)):
            for j in range(i+1, len(interrupted_list)):
                d1, d2 = interrupted_list[i], interrupted_list[j]
                dist = self.distance_between(d1, d2)
                if dist < self.action_threshold:
                    t1 = self.interrupt_time.get(d1, 0)
                    t2 = self.interrupt_time.get(d2, 0)
                    now = time.time()
                    if now - max(t1, t2) > 15:
                        return (d1, d2, dist)
        return None
        
    def can_resume(self, drone_id):
        """Check if interrupted drone can safely resume based on predicted positions."""
        if drone_id in self.interrupt_time:
            elapsed = time.time() - self.interrupt_time[drone_id]
            if elapsed < 5.0:
                return False
        
        for other_id in self.drones:
            if other_id != drone_id:
                # Check current distance
                current_dist = self.distance_between(drone_id, other_id)
                # Check predicted distance
                predicted_dist = self.predicted_distance_between(drone_id, other_id, 5.0)
                
                if current_dist < self.action_threshold or predicted_dist < self.min_separation:
                    return False
        return True
        
    def send_command(self, drone_id, command):
        self.client.publish(f"uav/{drone_id}/command", json.dumps(command))
        
    def interrupt_drone(self, drone_id):
        if drone_id not in self.interrupted:
            for _ in range(10):
                self.send_command(drone_id, {"type": "interrupt"})
                time.sleep(0.3)
            self.interrupted.add(drone_id)
            self.mission_status[drone_id] = "waiting"
            self.interrupt_time[drone_id] = time.time()
            self.interrupt_count[drone_id] = self.interrupt_count.get(drone_id, 0) + 1
            print(f"  [ATC] Interrupted UAV {drone_id}")
            
    def resume_drone(self, drone_id, waypoint):
        self.send_command(drone_id, {
            "type": "goto",
            "lat": waypoint["lat"],
            "lon": waypoint["lon"],
            "alt": waypoint["alt"]
        })
        self.interrupted.discard(drone_id)
        if drone_id in self.interrupt_time:
            del self.interrupt_time[drone_id]
        self.mission_status[drone_id] = "flying"
        print(f"  [ATC] Resumed UAV {drone_id}")
        
    def resolve_deadlock(self, deadlock_pair):
        """Resolve deadlock by raising the higher drone to a different altitude."""
        d1, d2, dist = deadlock_pair
        
        if int(d1) > int(d2):
            high_drone = d1
            low_drone = d2
        else:
            high_drone = d2
            low_drone = d1
            
        high_pos = self.get_position(high_drone)
        if high_pos:
            new_alt = high_pos[2] + 10
        else:
            new_alt = 25
            
        print(f"  [DEADLOCK] UAV {high_drone} and UAV {low_drone} deadlocked")
        print(f"  [DEADLOCK] Raising UAV {high_drone} to {new_alt}m")
        
        self.send_command(high_drone, {
            "type": "goto",
            "lat": high_pos[0],
            "lon": high_pos[1],
            "alt": new_alt
        })
        
        self.current_altitude[high_drone] = new_alt
        self.interrupted.discard(high_drone)
        if high_drone in self.interrupt_time:
            del self.interrupt_time[high_drone]
        self.mission_status[high_drone] = "flying"
        
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