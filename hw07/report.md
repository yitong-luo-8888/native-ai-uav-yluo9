# HW7 report — LLM clue-reasoning pipeline

> **Summary.** Default model (`claude-sonnet-5-5`): relevance and action
> accuracy **100%** on Lily's set (3 repeats, **93% action agreement**,
> $0.31) and on mine (1 run, $0.12). The traced failure came from the GUI's
> in-flight imagery (Ethan's cap filed as `log_only`). Its first wrong stage
> was Relevance, fixed in its schema and prompt (§5). End to end in new-gui
> (§6), AI proposals went through my HW6 validator, and the UAV flew the
> approved `hover_stream`s (and the injected `circle_stream`). One command
> starts it all: `bash hw07/run_demo.sh`. Still to add: the screen-recording link (§6).

## 1. What's where

| Piece | File(s) |
|---|---|
| Design | `hw07/design.md` |
| Schemas | `hw07/clues/messages.py` (`Description`, `Relevance`, `ClueDecision`) |
| Stages + StageSpecs (effort) | `hw07/clues/stages.py` |
| System prompts | `hw07/clues/prompts/{describe,relevance,decide}.md` |
| Pipeline, closer look, code guard, search centre | `hw07/clues/pipeline.py` |
| Backend | `hw07/clues/llm.py` (given; one change: effort isn't sent to `claude-haiku-4-5`, which rejects it; default model `claude-sonnet-5-5`) |
| Tools | `hw07/run_demo.sh` (one-command R7), `hw07/tools/gui_autostart.py`, `hw07/tools/record_mission.py`, `hw07/tools/replay_flight.py` (re-runs the pipeline on saved flight crops) |
| R8 unit tests (exactly three) | `hw07/clues/tests/test_pipeline.py` |
| Test set | `hw07/scenarios/lost-boy-north-gate/` (`scenario.json`, `make_icons.py`, `images/`), `hw07/clue_sets.csv` |
| **Planner hookup (R7)** | `hw06/planner/clue_hookup.py` (new), `hw06/planner/main.py` (wires it into `Planner`), `hw06/planner/validator.py` (circle-radius clamp + `notes`), `hw06/planner/config.py` (`min/max_circle_radius_m`), `hw06/tests/test_clue_hookup.py` (new) |
| Evidence | `hw07/evidence/` |

## 2. Unit tests (R8)

```
$ cd hw07/clues && python -m unittest discover tests -v
test_closer_look_happens_at_most_once ... ok
test_converge_search_centre_is_the_candidates_position ... ok
test_describe_sends_the_crop_and_none_of_the_missing_persons_details ... ok
Ran 3 tests in 0.835s
OK
```

1. **Describe is blind:** the request has exactly one image (the candidate's
   crop, byte for byte), and neither the text nor the system prompt contains
   the person's name, summary, last-seen text, or any clothing, belonging or
   "other" line.
2. **Closer look at most once:** Describe answers `needs_closer_look=true`
   every time and Decide answers `inspect_closer` every time. `closer_look`
   is called once, the calls are describe, describe, relevance, decide, and the
   code guard turns the final `inspect_closer` into `log_only`.
3. **Code sets the centre:** a scripted `converge_search` gets
   `search_center` equal to the candidate's lat/lon (not the last known point), and keeps the
   model's radius.

Planner side (`hw06`, pytest, no broker): `tests/test_clue_hookup.py` (6
tests) plus the existing 41. **47 passed** (`hw07/evidence/unit-hw06-clue-hookup.txt`).

I also smoke-tested the real `ClaudeBackend` → `beta.messages.parse` path with
a mocked HTTP transport (no key needed). The three schemas convert to valid
`output_config.format` JSON schemas, effort is sent per stage, parsed answers
validate, and the pipeline builds a contract-valid `ClueAssessment`.

## 3. Test set (R5)

`check_set.py ../../hw07/scenarios/lost-boy-north-gate --csv ../../hw07/clue_sets.csv` → **OK**
(`hw07/evidence/check_set.txt`).

Ethan, 8 (`people/boy-greenshirt.png`): 2 relevant clues (his navy cap with
the grey front, his orange backpack with the green dinosaur patch) and 4
decoys: a near miss (navy knit beanie: right colour, wrong kind of hat) plus
the three shared decoys. All six lie inside UAV 1's HW6 search route north
of the stadium. Why each one is there: `design.md`, Section 3.

## 4. Evaluation (R6)

Default model `claude-sonnet-5-5`, final prompts and schemas. Full traces:
`hw07/evidence/eval-lily-repeat3.txt` and `hw07/evidence/eval-ethan-repeat1.txt`.
Earlier runs: `evidence/before-fix/` (before the §5 fix) and `evidence/after-fix1/`
(after its first part). Both were also 100% with 93% agreement, so neither fix
cost accuracy on the offline sets.

```bash
cd lab/lesson7
python evaluate.py scenarios/lost-girl-pinafore --repeat 3
python evaluate.py ../../hw07/scenarios/lost-boy-north-gate --repeat 1
```

### Lily's set, 3 repeats

| clue | truth | object (last run) | relevance | action | rel ok | act ok |
|---|---|---|---|---|---|---|
| lp01 teddy | REL | brown plush teddy bear with red bow | high ×3 | converge_search ×3 | 3/3 | 3/3 |
| lp02 cardigan | REL | lime green button-up cardigan | high ×3 | converge_search ×3 | 3/3 | 3/3 |
| lp03 man's shoe | – | brown leather lace-up shoe | low ×2, none | log_only ×2, ignore | 3/3 | 3/3 |
| lp04 doll | – | doll with blond pigtails, pink dress | low ×3 | log_only ×3 | 3/3 | 3/3 |
| lp05 soccer ball | – | black and white soccer ball | none ×3 | ignore ×3 | 3/3 | 3/3 |

**Relevance accuracy 15/15 (100%), action accuracy 15/15 (100%), action
agreement across repeats 93%.** Only the shoe varied, between `log_only` and
`ignore`, and both are acceptable. **Cost $0.306** for 15 clue-runs (about $0.020 each), 142 s.

### Ethan's set (mine), 1 run

| clue | truth | object | relevance | action | rel ok | act ok |
|---|---|---|---|---|---|---|
| e01 navy cap, grey front | REL | blue baseball cap with grey front panels | high | converge_search (r = 90 m) | ✓ | ✓ |
| e02 orange dino backpack | REL | orange child's backpack with dinosaur patch | high | converge_search (r = 140 m) | ✓ | ✓ |
| e03 navy beanie (near miss) | – | blue knitted beanie with pompom | low | log_only | ✓ | ✓ |
| e04 man's shoe | – | brown lace-up shoe with cream laces | low | log_only | ✓ | ✓ |
| e05 doll | – | doll with blonde pigtails | none | ignore | ✓ | ✓ |
| e06 soccer ball | – | black and white soccer ball | low | log_only | ✓ | ✓ |

**Relevance 6/6 (100%), action 6/6 (100%). Cost $0.118**, 57 s.

**Where the cost goes** (21 clue-runs):

| stage | avg input tokens | avg output tokens | avg cost | avg latency |
|---|---:|---:|---:|---:|
| describe (effort medium, 1 image) | 1964 | 255 | $0.0065 | 2.8 s |
| relevance (effort medium) | 2313 | 210 | $0.0067 | 2.6 s |
| decide (effort low) | 1466 | 107 | $0.0040 | 2.2 s |

The closer look was taken 6 times on Lily ×3 and twice on Ethan's set, each
time because Describe asked (`needs_closer_look`, mostly to judge a shoe's
size). Decide never asked for one, and the code guard never had to override the
model. The model chose converge radii of 90–150 m, and the planner clamps the orbit to 40 m.

**Caveat:** these offline renders are much sharper than what the GUI camera
gives in flight (§6), so 100% offline overstates in-flight accuracy. That is
why the traced failure comes from flight imagery: offline, nothing went wrong.

## 5. Traced failure (R6): Ethan's cap filed away on in-flight imagery

**The wrong answer.** In the Stage-1 GUI run I saved the detector's real crops.
`hw07/tools/replay_flight.py` ran my pipeline on them exactly as `detector.py`
does in flight (`closer_look=None`). Ethan's cap (e01) came out
`relevance low → log_only`: his own cap would have been filed away and the drone
would have flown on (`evidence/replay-flight-before.txt`).

**Finding the first wrong stage**, call by call in the trace:

1. **Describe: not wrong.** On a blurry crop of about 20 pixels it said what it
   could see and admitted what it couldn't: "A blurry, roughly rectangular
   blue object … A large white-grey oval patch lies across the middle",
   `category: unknown`, `confidence: low`, `needs_closer_look: true`, ~21 cm.
   That is consistent with a navy cap with a grey front, and it didn't invent a label.
2. **Relevance: the first wrong stage.** It answered
   `"candidate_item": "blue denim shorts"`, listed mismatches against the
   shorts only, and gave `"relevance": "low"`. Its own rationale says: *"The navy cap
   with grey front panel is a possible alternative, but the object description
   does not clearly indicate a cap."* It saw the right item and still said `low`.
3. Decide then followed the policy correctly (`low → log_only`).

**Why it happened.** (a) The schema's single `candidate_item` field, written first, made
the model commit to one item before comparing any. It anchored on the first
blue item in the list (the shorts). (b) The prompt said nothing about an
*unclear* description, so "I can't tell what it is" counted as evidence against.

**The fix** (schema and prompt; no code changes):
- `messages.py`: a new field `possible_items` (every listed item it could be),
  placed **before** `candidate_item`, which becomes "the best of those".
- `prompts/relevance.md`: go through every listed item. When the description is
  unclear (low confidence, unknown category, needs a closer look) and its
  colours, markings, size **and outline** are consistent with a listed item,
  answer `medium` (a closer look settles it), not `low`.

**Before and after**, on the same in-flight crops
(`evidence/replay-flight-before.txt`, `replay-flight-after.txt`,
`replay-flight-after-closer-look.txt`; final-prompt rows are from replaying run 1's crops):

| crop | before | after (final prompt) |
|---|---|---|
| e01 Ethan's cap | low → **log_only** ✗ | **medium → inspect_closer** (in flight the planner hovers over it) |
| e01 + offline closer look (6× render) | – | "blue baseball cap with two light grey front panels" → **high → converge_search** ✓ |
| e02 backpack | high → converge_search | medium → inspect_closer |
| e03 beanie (near miss) | low → log_only | low → log_only |
| e05 doll | none → ignore | none → ignore |
| e06 soccer ball | low → log_only | none → ignore |

**The fix had a side effect, and correcting it took a second iteration.** The first
version of the rule ("colours, markings and size consistent") was too loose. In
full GUI run 1, the blurry soccer ball ("white five-lobed flower-shaped object")
became `medium`, "consistent with white sneakers", and earned a hover. Its
rationale even noted that "the flower-like lobed shape is odd". Adding the **outline**
("an outline that doesn't fit is a hard mismatch") brought the ball back to
`none`/`low` and the beanie to `low`, while the cap and backpack stayed at
`medium`. I confirmed this by replay on run 1's crops and again in full run 2. I
re-ran offline accuracy after each change, and it stayed at 100%.

**Lesson.** The first wrong stage was the one that turned honest uncertainty
into a confident "no". In a search, filing the person's own item away is the
worse error. A hover to check costs a minute of battery.

## 6. Part 2 — end to end (R7)

**Where the hookup lives:** `hw06/planner/clue_hookup.py` (new), wired into
`Planner.__init__` in `hw06/planner/main.py`. The circle-radius clamp is in
`hw06/planner/validator.py`, with its limits in `hw06/planner/config.py`.
How it works: `design.md`, Section 4. It's my real HW6 planner, not the
minimal-responder fallback.

**Processes:** `lab/` docker stack (mosquitto + 3 SITL + 3 drone backends),
`python -m planner.main` (hw06), and either `inject_clue.py` or
`detector.py --oracle` with new-gui. `bash hw07/run_demo.sh` starts **all of
it**: the docker stack, a SITL 1 restart (on the ground with a full battery, since
the simulated battery runs from 100% to 25% in about 5 minutes), new-gui with
the scene and camera set up, the planner, the detector and an MQTT recorder
(`hw07/tools/record_mission.py`). It logs everything to `hw07/evidence/e2e/<time>/`
(options: `--inject`, `--no-llm`, `--no-gui`).

**API spend for the whole homework:** about $2.0 (evaluations $1.2,
flight-crop replays $0.31, two full GUI runs $0.45, Haiku check $0.05).

The scene for the GUI:

```
$ python scenario_to_scene.py ../../hw07/scenarios/lost-boy-north-gate
Wrote .../gui/src/data/scene/saved/lost-boy-north-gate.json with 7 objects; clue images in .../gui/src/data/scene/clues
```

### Integration run 1 — `inject_clue.py` → validator → circle → COMPLETED ✅

Full log: `hw07/evidence/integration-inject.txt`. Repeated through the launcher:
`hw07/evidence/e2e/inject-via-run_demo/`.

```
$ python inject_clue.py 41.69915 -86.23745 --object "navy baseball cap with grey front" --radius 80 --mission lost-boy-north-gate
sent 0c85c025: navy baseball cap with grey front at 41.699150, -86.237450 -> converge_search

01:57:13 planner.clues: Approved AI circle_stream on UAV 1 for clue 0c85c025 (navy baseball cap with grey front)
         as 5c3e0d9f -- Circle radius 80 m clamped to 40 m (allowed 10-40 m).
01:57:13 mission/action_result {"request_id": "clue-0c85c025", "approved": true, "action_id": "5c3e0d9f",
         "type": "circle_stream", "uav": "1", "reasons": [], "notes": ["Circle radius 80 m clamped to 40 m
         (allowed 10-40 m)."], "decided_by": "ai", "assessment_id": "0c85c025", "proposal": "converge_search", ...}
01:57:13 mission/behavior_status ... "circle_stream", "state": "RUNNING", "detail": "flying to circle start (40 m north of target)"
01:57:30 mission/behavior_status ... "circle_stream", "state": "RUNNING", "detail": "circling at 40 m for 60 s"
01:57:30 uav/1/telemetry lat=41.6995098 lon=-86.2374489 alt_rel=19.988 activity=circling battery_level=0.65
   ...   (telemetry sweeps lat 41.69880-41.69951: a ~40 m orbit around 41.69915)
01:58:30 mission/behavior_status ... "circle_stream", "state": "COMPLETED", "detail": "circle_stream complete; resuming at waypoint 10 of 10"
```

What I saw: the model asked for 80 m, and the validator kept the proposal
but clamped the orbit to 40 m and said so in `notes`. The UAV flew to the
circle start due north of the centre, circled at 20 m altitude, reported
`COMPLETED`, and went back to the waypoint it had left.

In the same session I also checked the other mappings and the fence:

| Injected proposal | Verdict on `mission/action_result` | What flew |
|---|---|---|
| `inspect_closer` at the beanie (41.69937, −86.2369) | approved `hover_stream`, `decided_by: ai` | flew to 0 m standoff, hovered 60 s, `COMPLETED`, resumed route |
| `log_only` (soccer ball) | none published; planner log: `AI clue b699e8a2: soccer ball -> log_only; no flight (low)` | nothing |
| 2 × `converge_search` at 26% battery | **rejected**: "UAV 1 battery 26% is below the 25% reserve plus 8% circle_stream cost (33% needed)." | nothing |

The last row wasn't planned: SITL had drained the battery. It shows the
point of the homework, though. Two high-relevance AI proposals were refused by
the same validator rule that refuses an operator.

### Integration run 2 — `detector.py --oracle` over my set in new-gui ✅

One command starts everything, the GUI included: `bash hw07/run_demo.sh`. It
checks the key, runs `docker compose up -d`, restarts SITL 1 (on the ground,
battery 100%), writes the scene, then starts new-gui through
`hw07/tools/gui_autostart.py`. That wrapper builds the same window as
`new-gui.py`, shows only my saved scene, centres the map, and turns on UAV 1's
(Fuchsia) camera through the drone card's [C] handler. That replaces the two
clicks R7 otherwise needs, without editing the given GUI code. Finally it
starts the recorder, the planner and the detector, and prints every
proposal, verdict and status line.

**Stage-1 dry run (`--no-llm`, no key needed), `hw07/evidence/e2e/gui-stage1-no-llm/`.**
The GUI came up with the scene and the camera STREAMING, the planner took off
and flew the route, and `detector.py --oracle` found 5 of the 6 clues from the
GUI's real camera frames within 70 s, each at its exact scenario position. The
sixth, the shoe at the route's north edge, hadn't been reached when I stopped it:

```
02:17:02 clue-detector: CANDIDATE 0b9b0745 'unknown' (1.00) at (41.699050, -86.236500) from Fuchsia   (e05 doll)
02:17:25 clue-detector: CANDIDATE 2b99c35c 'unknown' (1.00) at (41.699150, -86.237450) from Fuchsia   (e01 cap)
02:17:44 clue-detector: CANDIDATE 94ccc25e 'unknown' (1.00) at (41.699480, -86.237200) from Fuchsia   (e06 ball)
02:17:46 clue-detector: CANDIDATE a2eaaf18 'unknown' (1.00) at (41.699370, -86.236900) from Fuchsia   (e03 beanie)
02:18:04 clue-detector: CANDIDATE 7a65ee3e 'unknown' (1.00) at (41.699600, -86.236600) from Fuchsia   (e02 backpack)
```

**Observation:** the in-flight crops (`flight-crops.png` there) are much
blurrier than `evaluate.py`'s offline renders, and they sit on parking-lot
satellite imagery instead of grass. The cap is a blue blob with a grey oval.
Offline accuracy will overstate in-flight accuracy. In flight I expect Describe
to ask for closer looks, which become `inspect_closer` → `hover_stream`.

**Full run 1 (the pipeline with the first version of the fix): `evidence/e2e/full-run-1/`.**
This run found the side effect described in §5 (the ball → `medium` → a hover),
and the duplicate problem: the detector re-reported the cap three times while UAV 1
hovered over it. Each repeat cost an LLM call and was rejected only because the
UAV was busy. It ended with the battery at 17%, with the last proposals rejected on reserve.

**Full run 2 (final pipeline and planner): `evidence/e2e/full-run-2/`.** This is the run to record.
`bash hw07/run_demo.sh`, 03:19–03:25, $0.21 for 12 assessments of 6 clues:

| time | clue | pipeline (in flight, no closer look) | verdict on `mission/action_result` | what flew |
|---|---|---|---|---|
| 03:21:01 | e05 doll | "small doll with blonde hair and pink dress": none → ignore | (no flight, logged) | – |
| 03:21:20 | e01 **cap** | "blue object with pale oval centre, unidentified": **medium → inspect_closer** | **approved** `hover_stream` 588d2c01, `decided_by: ai` | hovered over the cap 60 s → `COMPLETED` 03:22:29, resumed at waypoint 5 |
| 03:21:53, 03:22:21 | e01 again (detector re-report) | medium → inspect_closer | **rejected**: "UAV 1 is already executing hover_stream (action 588d2c01) …" and "A hover_stream within 5 m of this spot was already approved (action 588d2c01); not flying it again." | – |
| 03:22:53 | e06 ball | "white five-lobed flower-like object": low → log_only | (no flight, logged) | – |
| 03:23:01 | e03 **beanie (near miss)** | "dark blue knit beanie or hat": **low → log_only** | (no flight, logged) | – |
| 03:23:12 | e02 **backpack** | "orange item with a small green and white oval emblem": **medium → inspect_closer** | **approved** `hover_stream` 152ca37f | hovered 60 s → `COMPLETED` 03:24:29, resumed at waypoint 8 |
| 03:23:42, 03:24:13 | e02 again | medium → inspect_closer | rejected: busy + same spot | – |
| 03:24:55 | e04 man's shoe | "unidentified orange-brown elongated object": low → log_only | (no flight, logged) | – |

Each of the six clues ended with the right in-flight outcome. The two items of
Ethan's got a hover to look closer, and the four decoys flew nothing. No
`converge_search` happened in flight: no in-flight view was clear enough for
`high`. That is the conservative policy working, and it is also the main
limitation (see technical debt).

**Recording:** *(link to be added after recording `bash hw07/run_demo.sh`)*

**Screenshot (full run 3): `evidence/e2e/full-run-3-gui/`.** Oct. 15, 08:58–09:02, stopped
after 4½ minutes. `run_demo.sh` now saves a window grab every 30 s (`gui_autostart.py
--shots`). `screenshots/gui-0120s.png` was taken at 09:01:13, mid-hover: Fuchsia hovers over
Ethan's cap after the AI's `inspect_closer` was approved (09:00:38, `hover_stream` 5bcef7ec), and
the cap shows in its camera pane. The doll went to `log_only` (low; `ignore` in run 2, and both
are acceptable), and as in run 2, the cap's re-report was rejected (busy, same spot). Slide 6 uses this screenshot.

## 7. Technical debt

- **No in-flight escalation from hover to converge.** The planner's hover is the
  "closer look", but its frames don't go back into the pipeline as a *zoomed*
  candidate. The detector re-reports at normal zoom, and the same-spot rule
  drops those repeats. So in flight the AI never reaches `high` → `converge_search`. Closing that loop (a
  zoomed camera during `hover_stream`, with the detector marking those
  candidates `zoomed=True`) needs changes to the given detector and GUI.
- **Duplicate assessments cost money.** The given detector re-reports a clue
  while the UAV hovers over it: 12 assessments for 6 clues in run 2, about half
  the run's $0.21. My planner refuses the repeats, but the LLM calls have
  already been made. A dedup step in my pipeline (skip a candidate within 5 m of one
  already assessed) would fix it on my side.
- **Offline ≠ flight.** All six of Ethan's clues and all five of Lily's are 100% offline, but the
  in-flight crops are much blurrier. My set should include offline renders at
  flight blur, so `evaluate.py` catches what §5 found.
- The SITL battery drains from 100% to 25% in about 5 minutes, so a long demo
  starts rejecting everything on battery. `run_demo.sh` restarts SITL 1 for each
  run, which works around it without fixing the cause.
- `gui_autostart.py` reaches into private attributes of the given GUI
  (`_scene_pane`, `_cam_coordinator`, `_drone_store`), so a GUI update could break it.
- The circle radius is clamped to 10–40 m by the validator. The AI asks for
  30–150 m, so a "search" is really a close orbit of the clue. A real
  converge would fly an expanding square or a lawnmower over the radius, which my
  HW6 executor doesn't have.
- `ignore`/`log_only` proposals are only logged by the planner, not published
  anywhere an operator would see them.
