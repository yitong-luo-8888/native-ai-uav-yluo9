#!/usr/bin/env python3
"""ATC entry point: python start_tests.py <workload.json> <min-sep-m>"""

import sys
import json
import time
import threading
from atc import ATCController

EARTH_RADIUS_M = 6378137.0

def load_workload(filename):
    with open(filename) as f:
        return json.load(f)

class MissionRunner:
    def __init__(self, atc, workload):
        self.atc = atc
        self.workload = workload
        self.completed = []
        
    def run_all(self):
        threads = []
        for drone_id, missions in self.workload["missions"].items():
            t = threading.Thread(target=self._run_drone, args=(drone_id, missions))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
            
    def _run_drone(self, drone_id, missions):
        print(f"UAV {drone_id}: Starting")
        self.atc.send_command(drone_id, {"type": "arm"})
        time.sleep(3)
        
        for mission in missions:
            self._run_mission(drone_id, mission)
            
        self.atc.send_command(drone_id, {"type": "land"})
        print(f"UAV {drone_id}: Complete")
        
    def _run_mission(self, drone_id, mission):
        mission_id = mission["mission_id"]
        waypoints = mission["waypoints"]
        print(f"UAV {drone_id}: Mission {mission_id}")
        
        first_alt = waypoints[0]["alt"]
        self.atc.mission_status[drone_id] = "flying"
        self.atc.send_command(drone_id, {"type": "takeoff", "alt": first_alt})
        time.sleep(5)
        
        for i, wp in enumerate(waypoints):
            print(f"UAV {drone_id}: Waypoint {i+1}/{len(waypoints)}")
            self.atc.send_command(drone_id, {
                "type": "goto", "lat": wp["lat"], "lon": wp["lon"], "alt": wp["alt"]
            })
            self.atc.mission_status[drone_id] = "flying"
            
            deadline = time.time() + 120
            while time.time() < deadline:
                conflicts = self.atc.find_conflicts()
                for d1, d2, dist in conflicts:
                    if d1 == drone_id or d2 == drone_id:
                        other = d2 if d1 == drone_id else d1
                        if int(other) > int(drone_id):
                            self.atc.interrupt_drone(drone_id)
                
                if drone_id in self.atc.interrupted:
                    if all(self.atc.distance_between(drone_id, d) >= self.atc.min_separation 
                           for d in self.atc.drones if d != drone_id):
                        self.atc.resume_drone(drone_id, wp)
                    time.sleep(0.5)
                    continue
                
                if self.atc.distance_to_waypoint(drone_id, wp) < 2.0:
                    print(f"UAV {drone_id}: Reached waypoint {i+1}")
                    break
                time.sleep(0.5)
                
        print(f"UAV {drone_id}: Mission {mission_id} complete")
        self.completed.append((drone_id, mission_id))

def main():
    if len(sys.argv) != 3:
        print("Usage: python start_tests.py <workload.json> <min-separation-m>")
        sys.exit(1)
    
    workload_file = sys.argv[1]
    min_sep = float(sys.argv[2])
    
    print(f"=== ATC ===")
    print(f"Workload: {workload_file}")
    print(f"Min separation: {min_sep}m")
    
    workload = load_workload(workload_file)
    atc = ATCController(min_sep)
    
    print("Waiting for telemetry...")
    time.sleep(3)
    
    runner = MissionRunner(atc, workload)
    start = time.time()
    runner.run_all()
    elapsed = time.time() - start
    
    print(f"\n=== Results ===")
    print(f"Completed: {len(runner.completed)} missions")
    print(f"Time: {elapsed:.1f}s")
    
    time.sleep(3)

if __name__ == "__main__":
    main()
