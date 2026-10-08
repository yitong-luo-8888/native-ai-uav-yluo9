You are an expert Python engineer building a Human-on-the-Loop (HOTL) mission response
planner for a UAV simulation course (CSE 40701, HW6). Build the entire hw06/ deliverable
from scratch, matching the assignment spec exactly.


=====================================================================
READ THESE FIRST — DO NOT WRITE ANY CODE UNTIL YOU HAVE
=====================================================================
the root directory is ~/uav-native-ai
you will deliver everything in hw06
1. hw06/.claude/skill/uav-project-guide   ← AUTHORITATIVE project + test conventions. Obey it.
2. lab/lesson6/hotl_popup.py             ← MQTT contract ground truth
3. lab/lesson6/inject_event.py           ← event payload shape
4. lab/lesson6/mission_config.json       ← UAV, payload, battery costs, search route
5. lab/cv/person_event_detector.py       ← detector contract (given, not built)
6. lab/cv/geolocate.py                   ← pixel → lat/lon (given)
7. scripts/test_circle.py            ← circle start convention (due north)

If any of these paths do not exist, STOP and tell me before guessing. Do not invent
MQTT topics, payload fields, or command primitives.

After reading, print a summary in this exact form and then WAIT for my confirmation:

  PROJECT GUIDE RULES I WILL FOLLOW
    <list every rule you found in .claude/skill/uav-project-guide, verbatim or
     near-verbatim. Include any rules about testing, fakes, file layout,
     naming, imports, error handling, logging, and how to run things.>

  MQTT TOPICS AND PAYLOAD KEYS
    mission/events               : <exact keys>
    mission/decision_request     : <exact keys>
    mission/decision             : <exact keys>
    mission/action_result        : <exact keys>
    mission/behavior_status      : <exact keys>
    mission/cancel               : <exact keys>
    uav/<id>/command             : <primitives and parameters>
    uav/<id>/telemetry           : <keys you'll consume>

  CONFIG FACTS
    search route format, confidence threshold, battery reserve, response costs,
    payload list, default parameters.

Do not proceed until I reply "confirmed".

=====================================================================
GOAL
=====================================================================
A planner process that sits between the detector and the popup:

  mission/events ──► PLANNER ──► mission/decision_request ──► popup
                    (world model,  ◄── mission/decision ◄──── operator
                     candidates,   ──► mission/action_result
                     validator,    ──► mission/behavior_status
                     executor)     ◄── mission/cancel, mission/abort
                         │  ▲
           uav/1/command ▼  │ uav/1/telemetry
                       ArduPilot SITL

Requirements (all must be implemented):
R1 World model: UAV state (position, battery, payload, current behavior, route progress)
   and found persons ONLY (location, confidence, source, timestamp, decision status).
R2 Detections are uncertain evidence: explicit low-confidence policy. Below a chosen
   threshold, the menu offers only verify-only responses (hover_stream, circle_stream),
   NOT deliver. Justify threshold + policy in design.md. Cite the class frames
   (hit @ 0.26, false positive @ 0.31) as evidence.
R3 One decision per person: merge events within ~10 m of a known person; a decided person
   (responded to OR "No action") must never re-popup; a timed-out (undecided) person MAY
   be asked about again next time seen.
R4 Candidate responses: hover_stream, circle_stream, deliver. Each candidate carries
   eligible_uavs, default_uav, parameters (defaults from config), optional options.
R5 Decision loop through the popup: send decision_request, handle action / dismiss /
   timeout (enforce advertised timeout_s). Decision-maker MUST be behind an interface so
   an AI can replace the human next week without touching other code.
R6 Validator as its OWN STAGE: every action passes through it before anything flies,
   whoever chose it. At minimum: deliver needs item on board; battery must cover reserve
   plus response cost. Report every verdict on mission/action_result. On rejection, re-ask
   with the same event, a NEW request_id, and previous_rejection = [reason strings].
R7 Execution then resume: UAV flies search route; on approval it leaves the route, performs
   the response, reports PENDING/RUNNING/COMPLETED/FAILED/CANCELLED on
   mission/behavior_status, then resumes the route at the waypoint it was heading to.
   Cancel from popup stops the response and resumes the route.

Response flight behaviors:
  hover_stream:  fly to target (or standoff_m from it), hold for duration_s.
  circle_stream: orbit target at radius_m for duration_s; starts due NORTH of center.
  deliver:       fly to target, descend to delivery_alt_m, dwell, release, climb back out.

OUT OF SCOPE: multi-UAV simultaneous response, abort/RTL/critical-battery overrides,
restart survival, geofences/altitude limits, area search, follow-a-road.

=====================================================================
GUI VISUALIZATION (in addition to the given popup — keep the popup working)
=====================================================================
Build a separate live mission dashboard in hw06/planner/gui/, launchable as:

    python -m planner.gui.dashboard

It must show:
- Top-down map (PyQt5 QGraphicsView or pyqtgraph, no heavy deps): search route polyline
  with numbered waypoints; UAV as a heading-oriented arrow with trail; current segment
  highlighted; the "resume waypoint" marked distinctly; each person as a marker colored
  by decision status (unknown/pending/approved/dismissed/rejected/completed);
  hover_stream standoff ring and circle_stream orbit ring when active; deliver descent
  as a shrinking ring with altitude label.
- Right-hand state panel: UAV (position, battery bar+%, payload list, current_behavior,
  route progress); Persons table (id, lat, lon, confidence, source, status, action_id);
  selected person detail with candidate menu and last action_result reasons.
- Bottom event/decision log pane: timestamped, color-coded by direction, for every
  mission/* topic in and out.
- Toolbar: Inject Event, Simulate Timeout, Cancel current response, pause/follow toggle.
- READ-ONLY w.r.t. flight. Observes + injects + cancels; never flies the UAV.
- Real-time via background thread or QTimer bridge — never block the Qt event loop.

=====================================================================
DELIVERABLE LAYOUT
=====================================================================
hw06/
├── planner/
│   ├── __init__.py
│   ├── world_model.py
│   ├── person_registry.py
│   ├── candidates.py
│   ├── validator.py
│   ├── executor.py
│   ├── decision_source.py
│   ├── mqtt_bus.py
│   ├── config.py
│   ├── main.py
│   └── gui/
│       ├── __init__.py
│       ├── dashboard.py
│       └── widgets.py
├── tests/
│   ├── conftest.py
│   ├── test_person_registry.py
│   ├── test_candidates.py
│   ├── test_validator.py
│   ├── test_planner_loop.py
│   ├── test_decision_source.py
│   └── integration/
│       ├── conftest.py
│       ├── test_hover_resume.py
│       └── test_deliver_then_reject.py
├── pytest.ini
├── design.md
├── report.md
└── reflection.md

If .claude/skill/uav-project-guide specifies a different layout, naming, or
import style, FOLLOW THE GUIDE and note the divergence in design.md.

=====================================================================
TESTS — BEHAVIORAL SPEC (you write the code, I dictate what passes)
=====================================================================
Follow .claude/skill/uav-project-guide for all test conventions: structure,
naming, fixtures, fakes, how tests are organized, how they are run. Where this
section conflicts with the guide, the GUIDE WINS; note the conflict in report.md.

General rules (in addition to the guide):
- Unit tests use fakes only: no MQTT, no SITL, no YOLO, no docker. Total runtime
  under 2 s.
- The planner must be constructible with injected dependencies (bus, uav client,
  clock, decision source). If a design forces real MQTT in unit tests, change
  the design, not the test.
- Integration tests must self-skip (not fail) if SITL telemetry doesn't arrive
  within 10 s.
- Every test docstring must name the requirement (R1–R7) it covers.
- Provide wait/poll helpers for integration; never use fixed time.sleep as the
  primary synchronization.
- Provide fakes for Bus and UavClient, plus a frozen/scriptable Clock, so unit
  tests are deterministic.

---------------------------------------------------------------------
UNIT TESTS
---------------------------------------------------------------------

FILE: tests/test_person_registry.py
  test_merge_within_10m
    Two events ~5 m apart are the same person.
    Pass: one person; both event ids attached.
  test_split_beyond_10m
    Two events ~150 m apart are two people.
    Pass: two persons.
  test_confidence_updated_on_merge
    A higher-confidence re-sighting updates stored confidence.
    Pass: person.confidence equals the max.
  test_decided_person_no_repopup
    After RESPONDED, a new sighting does not need a decision.
    Pass: should_request_decision is False.
  test_dismissed_person_no_repopup
    After DISMISSED, same.
    Pass: should_request_decision is False.
  test_timedout_person_can_repopup
    After a timeout (UNDECIDED), a new sighting may be asked about again.
    Pass: should_request_decision is True.

FILE: tests/test_candidates.py
  test_low_conf_no_deliver
    Confidence 0.31 must not offer deliver.
    Pass: menu has hover_stream + circle_stream; no deliver.
  test_high_conf_has_deliver
    Confidence 0.80 offers all three.
    Pass: menu has hover_stream, circle_stream, deliver.
  test_parameters_come_from_config
    Defaults come from mission_config.json, not hardcoded.
    Pass: hover_stream defaults match config standoff_m and duration_s.
  test_deliver_options_include_kit
    Pass: options["item"] contains medical_kit.
  test_eligible_uavs_respect_payload
    A drone without the kit is not eligible for deliver.
    Pass: only the drone carrying medical_kit appears in eligible_uavs.

FILE: tests/test_validator.py
  test_valid_hover_approved
    Pass: approved True, reasons empty.
  test_deliver_without_kit_rejected
    Pass: approved False; a reason mentions medical_kit or payload.
  test_battery_reserve_rejected
    Cost would dip below reserve+buffer.
    Pass: approved False; a reason mentions battery.
  test_battery_boundary_approved
    Battery exactly equal to reserve + cost is approved (inclusive boundary).
    Pass: approved True.
  test_rejection_reasons_are_nonempty_strings
    Pass: every reason is a non-empty str.

FILE: tests/test_decision_source.py
  test_human_decision_source_returns_action
    Pass: returned action matches what was sent.
  test_human_decision_source_dismiss
    Pass: returns the dismiss sentinel, not an action.
  test_human_decision_source_timeout
    Pass: returns the timeout sentinel; elapsed ≈ timeout_s; no hang.
  test_decision_source_is_swappable
    A stub AI decision source with the same return shape substitutes with no
    planner changes.
    Pass: the decision-loop test passes with the AI stub substituted.

FILE: tests/test_planner_loop.py
  test_event_triggers_decision_request
    Pass: exactly one request for that event.
  test_dismiss_marks_person_decided
    Pass: status DISMISSED; request count unchanged on re-sighting.
  test_rejection_reask_carries_reasons
    Pass: new request_id; same event; previous_rejection == rejection reasons.
  test_timeout_marks_person_undecided
    Pass: status UNDECIDED, not DECIDED.
  test_low_confidence_restricts_menu
    Confidence 0.31 → candidates exclude deliver.
    Pass: no deliver in candidates.

---------------------------------------------------------------------
INTEGRATION TESTS — SITL + broker, self-skipping
---------------------------------------------------------------------

FILE: tests/integration/test_hover_resume.py   @pytest.mark.integration
  test_hover_stream_completes_and_resumes
    Person event → approve hover_stream → UAV flies → status reports
    PENDING, RUNNING, COMPLETED → resumes route at the SAME waypoint it was
    heading to before the response.
    Pass (all must hold):
      - decision_request within 2 s of event
      - action_result for hover approved
      - behavior_status shows PENDING then RUNNING then COMPLETED, in order
      - route.current_waypoint_index after completion == index captured before

FILE: tests/integration/test_deliver_then_reject.py   @pytest.mark.integration
  test_deliver_then_second_deliver_rejected
    First deliver succeeds and removes the kit. Second deliver for a different
    person is rejected; operator re-asked with reasons.
    Pass (all must hold):
      - first deliver: approved; medical_kit removed from payloads
      - second decision_request fires for the second person
      - second deliver: approved False; reasons mention missing item/payload
      - new decision_request with SAME event, NEW request_id,
        previous_rejection == rejection reasons

FILE: tests/integration/conftest.py
  real_stack fixture: connect localhost:1883 + uav/1; wait up to 10 s for
  telemetry else pytest.skip; build planner with real bus + real uav client +
  human decision source; run planner in background thread; tear down cleanly.
  Helpers: wait_until(predicate, timeout); wait_for_states(topic, key, states,
  timeout) returning the observed ordered list.

---------------------------------------------------------------------
STRETCH TESTS — @pytest.mark.stretch, same self-skip rule
---------------------------------------------------------------------

FILE: tests/integration/test_no_repopup.py
  test_same_person_reannounced_no_popup
    Pass: no additional decision_request published.

FILE: tests/integration/test_cancel_resume.py
  test_cancel_mid_response_resumes_route
    Pass: behavior_status reaches CANCELLED; route resumes at same waypoint.

---------------------------------------------------------------------
pytest.ini
  Markers integration and stretch; testpaths = tests; unit tests runnable
  with -m "not integration".

=====================================================================
DESIGN.md MUST CONTAIN
=====================================================================
1. Cleaned-up CRC cards: each class, responsibilities, collaborators.
2. A Mermaid sequence diagram: event arrives → operator approves hover_stream →
   UAV flies it → UAV resumes its route.
3. The named seam for next week: which class/interface an AI decision-maker
   replaces (DecisionSource) and exactly what it is handed (event + world_state +
   candidates + previous_rejection + timeout_s) and what it returns
   (action | dismiss | None).
4. The R2 low-confidence policy: threshold and justification, citing the 0.26
   hit and 0.31 false positive.
5. Any divergence between code and the CRC cards, with a one-line why.

=====================================================================
REPORT.md MUST CONTAIN
=====================================================================
- What works, what doesn't (technical debt, explicit).
- For every test file: exact command, raw output, one-sentence interpretation.
- For the two required integration tests: a dashboard screenshot taken while
  behavior is RUNNING, with the resume-waypoint marker visible on the map.
- One manual demo run with cv/person_event_detector.py in the loop (real YOLO
  events reaching the planner), noted as evidence the planner consumes real
  detector output.

=====================================================================
REFLECTION.md MUST CONTAIN
=====================================================================
- Where the design helped or got in the way.
- What surprised you when it flew.
- What you'd change before an AI starts making the decisions.
- "Lessons Learned" about using Claude, including what
  .claude/skill/uav-project-guide changed about your workflow.

=====================================================================
BUILD ORDER
=====================================================================
1. Read everything listed at the top. Print the guide rules + contract summary.
   Wait for "confirmed".
2. Write config.py and mqtt_bus.py.
3. Write world_model.py, person_registry.py.
4. Write candidates.py (incl. R2 policy) and validator.py.
5. Write decision_source.py (human interface first) and executor.py.
6. Write main.py wiring; get the popup working end-to-end with inject_event.py.
7. Write the dashboard GUI.
8. Write the fakes and unit tests. Run unit tests until green.
9. Write the two required integration tests (plus stretch).
10. Bring up the stack (docker compose up -d in lab/). Run integration tests.
11. Write design.md, report.md, reflection.md.
12. Run the acceptance self-check below and report raw output.

=====================================================================
STYLE / QUALITY BAR
=====================================================================
- Python 3.10+, type hints, dataclasses where sensible, no god-objects.
- Clear separation: world model / policy / validation / execution / GUI distinct.
- Every MQTT payload key matches lesson6/hotl_popup.py exactly.
- DecisionSource is a Protocol/ABC; HumanDecisionSource drives the popup round-trip;
  AIDecisionSource is a fully typed stub raising NotImplementedError.
- Timeout enforced with advertised timeout_s; timed-out persons become undecided.
- All flight goes through uav/<id>/command primitives ONLY (never direct MAVLink).
- Route resume stores the waypoint index the UAV was heading to BEFORE leaving.
- The GUI must be genuinely readable: labeled axes, legend, status colors, no overlap.
- If .claude/skill/uav-project-guide specifies anything stricter, follow the guide.

=====================================================================
ACCEPTANCE / SELF-CHECK BEFORE YOU DECLARE DONE
=====================================================================
Run these yourself and paste raw output before saying "done":
  1. cd hw06 && pytest tests/ -m "not integration" -v        → all green
  2. cd lab && docker compose up -d
     cd hw06 && pytest tests/integration -m integration -v -s → both required pass
     (skip only if SITL is genuinely down — say so explicitly)
  3. python lesson6/inject_event.py <lat> <lon> against a running planner:
     observed on dashboard: request → approval → RUNNING → COMPLETED → resume.
If any of these do not hold, do not claim success. Name what failed, paste the
output, and either fix it or record it in report.md as technical debt.

=====================================================================
WHEN DONE, GIVE ME
=====================================================================
- Full file tree of hw06/.
- Exact run commands (docker compose up -d, popup, planner, dashboard, inject).
- The two required integration test commands with a real output snippet.
- A "what to demo" script for the in-class check:
    * where a decision goes step by step (event → UAV moving)
    * what to change for an AI decision-maker and what stays the same
    * how the UAV knows which waypoint to resume to
    * the one-liner: "The operator chooses what should happen; the software
      decides whether it can, and then makes it happen."