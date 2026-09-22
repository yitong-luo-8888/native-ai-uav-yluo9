HW04 — Runtime Monitoring & Fault Injection
============================================

Prerequisites
-------------
- Docker + docker compose (for the lab stack)
- Python venv with paho-mqtt and pymavlink
  (from the repo root):
      python3 -m venv .venv
      source .venv/bin/activate
      pip install -r lab/backend/requirements.txt

Starting the lab stack
----------------------
    cd lab
    docker compose up -d --build
    docker logs lab-drone_backend_1-1 --tail 10
  Wait for "Heartbeat received..." and "Connected to MQTT broker...".

Running a normal flight
-----------------------
    cd lab
    source ../.venv/bin/activate
    python3 scripts/test_monitor_flight.py
  Flies a 40m square and lands (~2 minutes).

The plotter (Step 2)
--------------------
    cd hw04/plotting
    source ../../.venv/bin/activate
    python monitor_plot.py
  Live plots of GPS (top) and compass (bottom).

The GPS detector (Step 4)
-------------------------
    cd hw04/gps
    source ../../.venv/bin/activate
    python detector.py
  Prints "no problem" / "problem present" / "not enough data yet"
  with evidence, on every telemetry tick.

The compass detector (Step 4)
-----------------------------
    cd hw04/compass-mag
    source ../../.venv/bin/activate
    python detector.py

Injecting a fault (for testing the detectors)
---------------------------------------------
    cd lab
    source ../.venv/bin/activate

    # GPS fault:
    python3 scripts/mischief_maker.py GPS 10 60 High

    # Compass fault:
    python3 scripts/mischief_maker.py MAG-COMPASS 10 60 High

  Fires a randomized fault shortly after takeoff. Ctrl-C to reset.
  Run the detector in another terminal to watch it flip to
  "problem present", then back to "no problem" after Ctrl-C.

Notes
-----
- All clients (plotter, both detectors) publish the same monitor_config
  (["gps", "compass"]) so they can run in parallel without one
  overwriting another's request.
- Vehicle ID defaults to "1". Override with VEHICLE_ID=<n> if needed.
- Shut down with:  cd lab && docker compose down

Dependencies beyond lab/client2/requirements.txt
------------------------------------------------
None — the detectors use paho-mqtt (already required by the backend).