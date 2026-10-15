#!/usr/bin/env bash
# run_demo.sh -- HW7 Part 2 (R7) in ONE command: everything, GUI included.
#
#   bash hw07/run_demo.sh            # full run: GUI + planner + detector.py --oracle (your pipeline, real Claude)
#   bash hw07/run_demo.sh --no-llm   # same, but the detector runs Stage 1 only (no API key needed)
#   bash hw07/run_demo.sh --inject   # integration run 1: inject_clue.py instead of the detector
#   bash hw07/run_demo.sh --no-gui   # everything except the GUI
#
# In order, it:
#   1. checks the API key (unless --no-llm/--inject; falls back to --no-llm if it doesn't work)
#   2. brings the lab/ docker stack up (broker, SITL, drone backends) and waits for UAV 1 telemetry
#   3. restarts SITL 1 so UAV 1 is on the ground with a full battery (the camera records
#      ground level when it sees the drone arm, and the SIM battery lasts ~5 min)
#   4. writes the scene (scenario_to_scene.py)
#   5. starts new-gui via hw07/tools/gui_autostart.py: shows the scene, centres the map,
#      turns UAV 1's (Fuchsia) camera on -- the two clicks R7 otherwise needs
#   6. starts the MQTT recorder, the HW6 planner (takes off, flies the route) and the detector
#   7. prints every proposal, verdict and status line until you press Ctrl+C or close the GUI
#
# Logs: hw07/evidence/e2e/<timestamp>/{gui,planner,detector,docker}.log and topics.log;
# GUI screenshots every 30 s in screenshots/.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/hw07/evidence/e2e/$(date +%Y%m%d-%H%M%S)"
SCENARIO="$ROOT/hw07/scenarios/lost-boy-north-gate"
MODE=detector; LLM=1; GUI=1
for arg in "$@"; do
    case "$arg" in
        --inject) MODE=inject ;;
        --no-llm) LLM=0 ;;
        --no-gui) GUI=0 ;;
        *) echo "unknown option $arg"; exit 2 ;;
    esac
done
mkdir -p "$OUT"
PIDS=()
step() { echo; echo "== $*"; }

cleanup() {
    trap - INT TERM
    echo; echo "Stopping everything this script started..."
    for pid in "${PIDS[@]}"; do kill -INT "$pid" 2>/dev/null; done
    sleep 2
    for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null; done
    echo "Logs in $OUT"
    exit 0
}
trap cleanup INT TERM

uav1() {   # uav1 <python condition on telemetry dict t>: wait until it holds
    for _ in $(seq 1 90); do
        "$PY" - "$1" <<'EOF' 2>/dev/null && return 0
import json, sys, time
import paho.mqtt.client as mqtt
seen = []
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.on_connect = lambda c, *a: c.subscribe("uav/1/telemetry")
c.on_message = lambda c, u, m: seen.append(json.loads(m.payload))
c.connect("localhost", 1883); c.loop_start(); time.sleep(2); c.loop_stop()
t = seen[-1] if seen else None
sys.exit(0 if t is not None and eval(sys.argv[1]) else 1)
EOF
        sleep 2
    done
    return 1
}

# 1. API key
if [[ $MODE == detector && $LLM == 1 ]]; then
    step "1/7 Checking the API key (testllm.py, a fraction of a cent)"
    if (cd "$ROOT/lab/lesson7" && "$PY" testllm.py) > "$OUT/testllm.log" 2>&1; then
        echo "key OK"
    else
        grep -E "FAILED|not set" "$OUT/testllm.log"
        echo "!! No working key: falling back to --no-llm (Stage 1 only, nothing reaches the planner)."
        LLM=0
    fi
fi

# 2. docker stack
step "2/7 Docker stack (lab/)"
if ! docker info >/dev/null 2>&1; then
    echo "!! Docker isn't reachable from WSL. Start Docker Desktop (Settings > Resources > WSL integration > Ubuntu on), then re-run."
    exit 1
fi
(cd "$ROOT/lab" && docker compose up -d) > "$OUT/docker.log" 2>&1 || { cat "$OUT/docker.log"; exit 1; }
uav1 't is not None' || { echo "!! no uav/1/telemetry on the broker"; exit 1; }
echo "broker and UAV 1 telemetry up"

# 3. fresh UAV 1
step "3/7 Restarting SITL 1 (on the ground, battery 100%)"
(cd "$ROOT/lab" && docker compose restart sitl_1 drone_backend_1) >> "$OUT/docker.log" 2>&1
uav1 '(t.get("battery_level") or 0) >= 0.99 and not t.get("armed")' || { echo "!! UAV 1 didn't come back"; exit 1; }
echo "UAV 1 landed, battery 100%"

# 4. scene
step "4/7 Scene for new-gui"
(cd "$ROOT/lab/lesson7" && "$PY" scenario_to_scene.py "$SCENARIO")

# 5. GUI
GUI_PID=""
if [[ $GUI == 1 ]]; then
    step "5/7 new-gui (the window opens on your desktop via WSLg)"
    "$PY" -u "$ROOT/hw07/tools/gui_autostart.py" --shots "$OUT/screenshots" --every 30 > "$OUT/gui.log" 2>&1 & GUI_PID=$!; PIDS+=($GUI_PID)
    for _ in $(seq 1 60); do grep -q "camera Fuchsia: STREAMING" "$OUT/gui.log" && break
        kill -0 "$GUI_PID" 2>/dev/null || { echo "!! GUI exited:"; tail -n 20 "$OUT/gui.log"; cleanup; }
        sleep 1; done
    grep "^\[gui\]" "$OUT/gui.log"
    grep -q "camera Fuchsia: STREAMING" "$OUT/gui.log" || \
        echo "!! Camera not confirmed on: click the camera [C] button on the Fuchsia drone card (right panel)."
else
    step "5/7 GUI skipped (--no-gui)"
fi

# 6. recorder, planner, detector
step "6/7 Recorder, planner, $MODE"
"$PY" "$ROOT/hw07/tools/record_mission.py" "$OUT/topics.log" & PIDS+=($!)
(cd "$ROOT/hw06" && exec "$PY" -u -m planner.main) > "$OUT/planner.log" 2>&1 & PIDS+=($!)
echo "planner: taking off, then flying the search route (log planner.log)"
if [[ $MODE == inject ]]; then
    until grep -q '"search_route", "state": "RUNNING"' "$OUT/topics.log" 2>/dev/null; do sleep 2; done
    (cd "$ROOT/lab/lesson7" && "$PY" inject_clue.py 41.69915 -86.23745 --mission lost-boy-north-gate \
        --object "navy baseball cap with grey front" --radius 80) | tee "$OUT/inject.txt"
else
    extra=(); [[ $LLM == 0 ]] && extra=(--no-llm)
    (cd "$ROOT/lab/lesson7" && exec "$PY" -u detector.py "$SCENARIO" --oracle "${extra[@]}") \
        > "$OUT/detector.log" 2>&1 & PIDS+=($!)
    echo "detector.py --oracle ${extra[*]} (log detector.log)"
fi

# 7. follow
step "7/7 Live: proposals (mission/clues), verdicts (mission/action_result), status. Ctrl+C to stop."
tail -n +1 -F "$OUT/topics.log" 2>/dev/null | grep --line-buffered -E "mission/(clues|action_result|behavior_status)" & PIDS+=($!)
[[ $MODE == detector ]] && { tail -n 0 -F "$OUT/detector.log" 2>/dev/null | grep --line-buffered -E "CANDIDATE|ASSESSED|failed" & PIDS+=($!); }
if [[ -n $GUI_PID ]]; then
    while kill -0 "$GUI_PID" 2>/dev/null; do sleep 1; done
    echo "GUI closed."
    cleanup
fi
wait
