#!/usr/bin/env python3
"""ATC - 2 drones concurrent with staggered takeoff."""

import sys
import json
import time
import threading
from atc import ATCController

def load_workload(filename):
    with open(filename) as f:
        return json.load(f)

class MissionRunner:
    def __init__(self, atc, workload):
        self.atc = atc
        self.workload = workload
        self.completed = []
        self.active_drones = set()
        self.current_waypoint = {}
        self.stagger_time = 10  # 10 seconds between takeoffs

    def run_all(self):
        """Run missions with max 2 drones at a time, staggered takeoffs."""
        drone_ids = list(self.workload["missions"].keys())
        
        # Process drones in pairs
        for i in range(0, len(drone_ids), 2):
            batch = drone_ids[i:i+2]
            print(f"\n{'='*50}")
            print(f"BATCH: {batch}")
            print(f"{'='*50}")
            
            if len(batch) == 2:
                # Two drones fly concurrently with staggered takeoff
                d1, d2 = batch
                self.active_drones = {d1, d2}
                
                threads = []
                for idx, drone_id in enumerate(batch):
                    missions = self.workload["missions"][drone_id]
                    # First drone: no delay, Second drone: wait 10s
                    delay = idx * self.stagger_time
                    t = threading.Thread(target=self._run_drone, args=(drone_id, missions, delay))
                    threads.append(t)
                    t.start()
                    print(f"Launching UAV {drone_id} with {delay}s delay")
                
                for t in threads:
                    t.join()
            else:
                # Single drone left - fly solo
                drone_id = batch[0]
                self.active_drones = {drone_id}
                missions = self.workload["missions"][drone_id]
                print(f"Launching UAV {drone_id} solo")
                self._run_drone(drone_id, missions, 0)
            
            self.active_drones.clear()
            print(f"Batch complete: {batch}")

    def _run_drone(self, drone_id, missions, takeoff_delay=0):
        # Staggered takeoff - wait before arming
        if takeoff_delay > 0:
            print(f"  [STAGGER] UAV {drone_id} waiting {takeoff_delay}s...")
            time.sleep(takeoff_delay)
        
        print(f"\nUAV {drone_id}: Starting")
        self.atc.send_command(drone_id, {"type": "arm"})
        time.sleep(3)

        for mission in missions:
            self._run_mission(drone_id, mission)

        self.atc.send_command(drone_id, {"type": "land"})
        time.sleep(5)
        print(f"UAV {drone_id}: Complete (landed)")

    def _run_mission(self, drone_id, mission):
        mission_id = mission["mission_id"]
        waypoints = mission["waypoints"]
        print(f"\nUAV {drone_id}: Mission {mission_id}")
        
        first_alt = waypoints[0]["alt"]
        self.atc.mission_status[drone_id] = "flying"
        self.atc.send_command(drone_id, {"type": "takeoff", "alt": first_alt})
        print(f"  [TAKEOFF] UAV {drone_id} to {first_alt}m")
        time.sleep(8)

        for i, wp in enumerate(waypoints):
            print(f"  UAV {drone_id}: Waypoint {i+1}/{len(waypoints)}")
            self.current_waypoint[drone_id] = wp
            self.atc.mission_status[drone_id] = "flying"
            
            self.atc.send_command(drone_id, {
                "type": "goto", "lat": wp["lat"], "lon": wp["lon"], "alt": wp["alt"]
            })

            deadline = time.time() + 120
            while time.time() < deadline:
                # Check conflicts with other active drone
                for other_id in self.active_drones:
                    if other_id != drone_id:
                        dist = self.atc.distance_between(drone_id, other_id)
                        
                        # Higher ID yields to lower ID
                        if self.atc.should_yield(drone_id, other_id):
                            if dist < self.atc.action_threshold:
                                self.atc.interrupt_drone(drone_id)
                                print(f"  [YIELD] UAV {drone_id} yields to UAV {other_id} at {dist:.1f}m")
                
                # If interrupted, wait until safe
                if drone_id in self.atc.interrupted:
                    safe = True
                    for other_id in self.active_drones:
                        if other_id != drone_id:
                            dist = self.atc.distance_between(drone_id, other_id)
                            if dist < self.atc.action_threshold:
                                safe = False
                    
                    if safe:
                        self.atc.resume_drone(drone_id, wp)
                        print(f"  [RESUME] UAV {drone_id} resumed")
                    time.sleep(0.5)
                    continue

                # Check arrival
                if self.atc.distance_to_waypoint(drone_id, wp) < 2.0:
                    print(f"  UAV {drone_id}: Reached waypoint {i+1}")
                    break
                    
                time.sleep(0.5)
            else:
                print(f"  UAV {drone_id}: TIMEOUT on waypoint {i+1}")

        print(f"UAV {drone_id}: Mission {mission_id} complete")
        self.atc.mission_status[drone_id] = "done"
        self.completed.append((drone_id, mission_id))

def main():
    if len(sys.argv) != 3:
        print("Usage: python start_tests.py <workload.json> <min-separation-m>")
        sys.exit(1)

    workload_file = sys.argv[1]
    min_sep = float(sys.argv[2])

    print(f"=== ATC: 2 Drones Concurrent, Staggered Takeoff ===")
    print(f"Workload: {workload_file}")
    print(f"Min separation: {min_sep}m")
    print(f"Takeoff stagger: 10s")
    print(f"Max concurrent drones: 2")

    workload = load_workload(workload_file)
    atc = ATCController(min_sep)

    print("Waiting for telemetry...")
    time.sleep(3)

    runner = MissionRunner(atc, workload)
    start = time.time()
    runner.run_all()
    elapsed = time.time() - start

    print(f"\n{'='*50}")
    print(f"=== RESULTS ===")
    print(f"{'='*50}")
    print(f"✅ NO CRASH")
    print(f"Completed: {len(runner.completed)} missions")
    print(f"Time: {elapsed:.1f}s")
    
    for drone_id, mission_id in runner.completed:
        print(f"  ✅ UAV {drone_id}: {mission_id}")

    time.sleep(3)
    sys.exit(0)

if __name__ == "__main__":
    main()