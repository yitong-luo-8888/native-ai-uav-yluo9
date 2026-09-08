# Reflection on ATC Design

## What I Tried

I started with a fully concurrent approach where all drones flew simultaneously with velocity-based conflict prediction. This was ambitious but difficult to debug. The drones moved too fast for the interrupt mechanism to prevent separation violations.

I then tried implementing speed control by periodically interrupting drones to slow them down. While this helped with separation, it caused mission timeouts because drones were too slow.

I also attempted deadlock detection based on position history, checking if drones had moved less than 1 meter in 5 seconds. This added complexity but didn't solve the fundamental issue of drones moving too fast for reactive conflict detection.

## Flaws Found

The main flaw was that drones fly at full speed (~5 m/s) and cannot be commanded to fly slower. The only speed control available is full stop (interrupt). This means drones cover significant distance during the time it takes to detect a conflict and send an interrupt command.

Another issue was that sending interrupt commands multiple times took too long. By the time the interrupt took effect, the drones had already gotten too close.

## How I Addressed Them

I simplified the design significantly. Instead of trying to control speed or predict conflicts, I limited concurrency to two drones at a time with staggered takeoffs. The 10-second stagger ensures drones don't launch simultaneously.

For conflict resolution, I implemented a simple priority rule: higher ID yields to lower ID. This is deterministic and easy to reason about.

## Where Design Still Falls Short

The design is conservative and doesn't make full use of airspace. With three drones, one drone always waits while the other two fly. Performance could be better with all three drones flying simultaneously.

The priority rule doesn't consider mission progress. A drone nearly at its waypoint might be interrupted just because it has a higher ID.

The system doesn't handle edge cases like lost drones, communication failures, or unexpected drone behavior.