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
        self.failed = []
        self.crash_detected = False
        self.current_waypoint = {}

    def log_distances(self, event=""):
        """Log distances between all drone pairs."""
        drone_ids = sorted(self.atc.drones.keys())
        if len(drone_ids) < 2:
            return
        
        distances = []
        for i in range(len(drone_ids)):
            for j in range(i+1, len(drone_ids)):
                d1, d2 = drone_ids[i], drone_ids[j]
                dist = self.atc.distance_between(d1, d2)
                distances.append(f"UAV{d1}-UAV{d2}: {dist:.1f}m")
        
        print(f"    [DIST] {' | '.join(distances)}")

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
        self.log_distances("start")
        self.atc.send_command(drone_id, {"type": "arm"})
        time.sleep(3)

        for mission in missions:
            if self.crash_detected:
                break
            success = self._run_mission(drone_id, mission)
            if not success:
                self.failed.append((drone_id, mission["mission_id"]))

        self.atc.send_command(drone_id, {"type": "land"})
        print(f"UAV {drone_id}: Complete")

    def _run_mission(self, drone_id, mission):
        mission_id = mission["mission_id"]
        waypoints = mission["waypoints"]
        print(f"UAV {drone_id}: Mission {mission_id}")

        first_alt = waypoints[0]["alt"]
        self.atc.mission_status[drone_id] = "flying"
        self.atc.send_command(drone_id, {"type": "takeoff", "alt": first_alt})
        print(f"  [TAKEOFF] UAV {drone_id} to {first_alt}m")
        self.log_distances("takeoff")
        
        # Wait for takeoff
        time.sleep(8)

        for i, wp in enumerate(waypoints):
            print(f"UAV {drone_id}: Waypoint {i+1}/{len(waypoints)}")
            self.current_waypoint[drone_id] = wp
            self.atc.mission_status[drone_id] = "flying"
            
            self.atc.send_command(drone_id, {
                "type": "goto", "lat": wp["lat"], "lon": wp["lon"], "alt": wp["alt"]
            })
            print(f"  [GOTO] UAV {drone_id} to ({wp['lat']:.6f}, {wp['lon']:.6f}, {wp['alt']}m)")
            self.log_distances("goto")

            deadline = time.time() + 120
            while time.time() < deadline:
                # CHECK CRASH FIRST - if any drones within min_separation = CRASH
                crashed, d1, d2, dist = self.atc.check_crash()
                if crashed:
                    self.crash_detected = True
                    print(f"  [CRASH] UAV {d1} and UAV {d2} within min separation: {dist:.2f}m < {self.atc.min_separation}m")
                    self.log_distances("crash")
                    return False
                
                # Check for approaching conflicts (using predicted positions)
                conflicts = self.atc.find_conflicts()
                for d1, d2, current_dist, predicted_dist in conflicts:
                    if d1 == drone_id or d2 == drone_id:
                        other = d2 if d1 == drone_id else d1
                        # Interrupt the higher ID drone
                        if int(other) > int(drone_id):
                            if drone_id not in self.atc.interrupted:
                                self.atc.interrupt_drone(drone_id)
                                print(f"  [WARNING] UAV {drone_id} approaching UAV {other} (current: {current_dist:.1f}m, predicted: {predicted_dist:.1f}m)")
                                self.log_distances("approaching")
                        else:
                            if other not in self.atc.interrupted:
                                self.atc.interrupt_drone(other)
                                print(f"  [WARNING] UAV {other} approaching UAV {drone_id} (current: {current_dist:.1f}m, predicted: {predicted_dist:.1f}m)")
                                self.log_distances("approaching")
                
                # Check deadlock
                deadlock = self.atc.detect_deadlock()
                if deadlock:
                    d1, d2, dist = deadlock
                    print(f"  [DEADLOCK] UAV {d1} and UAV {d2} deadlocked at {dist:.1f}m")
                    self.log_distances("deadlock")
                    self.atc.resolve_deadlock(deadlock)
                    self.log_distances("after deadlock resolution")
                
                # If interrupted, wait for safe resume
                if drone_id in self.atc.interrupted:
                    if self.atc.can_resume(drone_id):
                        self.atc.resume_drone(drone_id, wp)
                        print(f"  [RESUME] UAV {drone_id} resuming (safe distance restored)")
                        self.log_distances("resume")
                    time.sleep(0.5)
                    continue

                # Check arrival
                if self.atc.distance_to_waypoint(drone_id, wp) < 2.0:
                    print(f"UAV {drone_id}: Reached waypoint {i+1}")
                    self.log_distances("arrival")
                    break
                    
                time.sleep(0.5)
            else:
                print(f"UAV {drone_id}: TIMEOUT on waypoint {i+1}")
                self.log_distances("timeout")
                return False

        print(f"UAV {drone_id}: Mission {mission_id} complete")
        self.log_distances("mission complete")
        self.atc.mission_status[drone_id] = "done"
        self.completed.append((drone_id, mission_id))
        return True

def main():
    if len(sys.argv) != 3:
        print("Usage: python start_tests.py <workload.json> <min-separation-m>")
        sys.exit(1)

    workload_file = sys.argv[1]
    min_sep = float(sys.argv[2])

    print(f"=== ATC ===")
    print(f"Workload: {workload_file}")
    print(f"Min separation (CRASH threshold): {min_sep}m")
    print(f"Action threshold (interrupt early): {min_sep + 10}m")
    print(f"Any drones within {min_sep}m = CRASH = MISSION FAILED")

    workload = load_workload(workload_file)
    atc = ATCController(min_sep)

    print("Waiting for telemetry...")
    time.sleep(3)

    runner = MissionRunner(atc, workload)
    start = time.time()
    runner.run_all()
    elapsed = time.time() - start

    print(f"\n=== Results ===")
    if runner.crash_detected:
        print("❌ CRASH DETECTED - DRONES VIOLATED MIN SEPARATION")
    else:
        print("✅ SUCCESS - MIN SEPARATION MAINTAINED AT ALL TIMES")
    
    print(f"Completed: {len(runner.completed)} missions")
    print(f"Failed: {len(runner.failed)} missions")
    print(f"Time: {elapsed:.1f}s")
    
    for drone_id, mission_id in runner.completed:
        print(f"  ✅ UAV {drone_id}: {mission_id}")
    
    for drone_id, mission_id in runner.failed:
        print(f"  ❌ UAV {drone_id}: {mission_id} FAILED")

    time.sleep(3)
    sys.exit(1 if runner.crash_detected else 0)

if __name__ == "__main__":
    main()