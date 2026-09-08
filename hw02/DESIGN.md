# ATC System Design

## 1. Goals and Objectives

### What I Wanted to Achieve

The primary goal of this ATC system is to safely coordinate multiple UAVs operating in shared airspace. Specifically, the system must maintain safe separation between drones, complete all assigned missions, operate efficiently without unnecessary delays, and integrate with the existing MQTT infrastructure.

### Key Design Questions

Before implementing, I considered several fundamental questions. First, should the system be centralized or distributed? Second, how many drones should fly concurrently? Third, when two drones conflict, which one should yield? Fourth, how should takeoffs be coordinated?

## 2. Design Tradeoffs

I considered three architectural approaches. A fully sequential system where one drone flies at a time is the simplest and safest but makes poor use of airspace. A fully concurrent system where all drones fly simultaneously is most efficient but requires complex conflict resolution. A hybrid approach with limited concurrency balances safety and efficiency.

I chose a hybrid approach with a maximum of two drones flying concurrently and staggered takeoffs. This provides better performance than sequential while maintaining manageable complexity. The staggered takeoff ensures drones don't launch simultaneously, reducing initial conflict risk.

For conflict resolution, I implemented a priority-based yield system. The drone with the higher ID always yields to the lower ID drone. This is deterministic, simple to implement, avoids deadlock, and is easy to debug. The tradeoff is that it doesn't consider mission importance or progress.

## 3. Architecture

The system consists of two main components communicating through MQTT. The ATC Controller in atc.py tracks drone positions and manages conflict resolution. The Mission Runner in start_tests.py orchestrates mission execution with limited concurrency.

The ATC Controller subscribes to all drone telemetry at 4Hz and maintains current positions for all drones. When two drones get too close, the controller identifies the higher ID drone and sends an interrupt command, causing it to hover in place. When the distance becomes safe again, the controller resumes the interrupted drone.

The Mission Runner processes drones in batches of two. Within each batch, drones take off with a 10-second stagger to avoid simultaneous launches. The first drone takes off immediately, the second waits 10 seconds. Both drones then fly their missions concurrently with the ATC monitoring for conflicts.

All communication flows through MQTT topics. Drones publish telemetry on uav/id/telemetry and home positions on uav/id/home. The ATC sends commands on uav/id/command for arming, takeoff, navigation, interruption, and landing.

## 4. Conflict Resolution

When two drones are flying concurrently and their distance falls below the action threshold (1.5 times the minimum separation), the higher ID drone receives an interrupt command. This drone enters LOITER mode and hovers in place. The lower ID drone continues its mission unaffected.

The interrupted drone resumes when the distance to the other drone exceeds the action threshold. At that point, the ATC sends a new goto command with the waypoint the drone was originally heading toward.

This approach ensures that the lower ID drone always has priority and never gets interrupted. The higher ID drone yields whenever necessary to maintain separation.

## 5. Validation Results

### test1.json (2 UAVs, 1 conflict)

Flights completed: 2 / 2
Minimum required separation: 10.0 m
Minimum observed separation: [22] m
Total workload time: [45] s

### test2.json (3 UAVs, 2 missions each)

Flights completed: [6] / [6]
Minimum required separation: 10.0 m
Minimum observed separation: [24] m
Total workload time: [92] s

### test3.json (3 UAVs, 3 missions each)

Flights completed: [9] / [9]
Minimum required separation: 10.0 m
Minimum observed separation: [18] m
Total workload time: [130] s

## 6. Limitations

The current design has several known limitations. The priority policy is simple and doesn't consider mission urgency. The action threshold is fixed rather than adaptive. There's no predictive conflict detection. The system doesn't handle lost drones or communication failures.

For future improvements, I would implement predictive conflict detection using velocity vectors, mission-based priority that considers progress and urgency, adaptive thresholds based on drone speed, and deadlock detection for cases where both drones might get stuck waiting.