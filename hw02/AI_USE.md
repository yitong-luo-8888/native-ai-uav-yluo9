# AI Use Log

## How I Used AI

I used DeepSeek as an AI assistant throughout this assignment, primarily for understanding the MQTT architecture, exploring design options, and debugging implementation issues. My approach was to implement features step by step, ensuring I fully understood each component before moving to the next. I believe a complete and reliable understanding of the MQTT architecture is a prerequisite for any further design work.

## Where AI Helped

DeepSeek was valuable in explaining the MQTT publish/subscribe pattern and how the existing UAV infrastructure uses topics for telemetry and commands. It helped me understand the command contract (arm, takeoff, goto, interrupt, land) and how the backend translates MQTT messages to MAVLink commands for the SITL drones.

DeepSeek also helped with environment setup issues, including Docker configuration, WSL2 integration, and Python virtual environment management. The troubleshooting guidance saved significant time.

For the ATC design, DeepSeek generated initial code structures and helped me understand the tradeoffs between different architectural approaches.

## Where AI Didn't Help

DeepSeek initially suggested multiple complex designs involving velocity prediction, speed control through periodic interrupts, and deadlock detection based on position history. These approaches were theoretically sound but failed in practice.

The core issue was that drones fly at non-linear speeds, making state prediction extremely challenging. The drones don't maintain constant velocity - they accelerate, decelerate, and respond to commands with variable latency. This made velocity-based prediction unreliable.

DeepSeek's suggested speed control mechanism (periodically interrupting drones to slow them down) caused mission timeouts because drones became too slow to reach waypoints within the deadline.

The deadlock detection logic, while interesting, added complexity without solving the fundamental problem of maintaining separation.

## How I Overrode AI Suggestions

After multiple failed attempts with complex designs, I decided to simplify significantly. Instead of trying to predict drone trajectories or control their speed, I limited concurrency to two drones at a time with staggered takeoffs. This eliminates most conflict scenarios entirely.

For the conflicts that do occur with two drones in the air, I implemented a simple priority rule: higher ID yields to lower ID. This is deterministic, easy to reason about, and reliable.

Previous attempts all had the same fundamental flaw: they could not reliably work for any separation distance. The complex prediction and speed control systems worked for some values but failed for others. The simple priority-based approach works consistently regardless of separation distance.

## Insights

I learned that AI is excellent for explaining concepts and generating boilerplate code but struggles with physical system constraints that aren't explicitly stated. DeepSeek didn't initially understand that drones have non-linear speed profiles and that interrupts have significant latency.

The most important lesson was that simplicity beats complexity when dealing with physical systems. A simple, conservative design that works reliably is better than a complex, efficient design that fails unpredictably.

I also learned that understanding the architecture deeply before designing is essential. The MQTT contract, command latency, and drone behavior all constrain what's possible. AI can help explore the design space, but the final decisions require hands-on testing and iteration.