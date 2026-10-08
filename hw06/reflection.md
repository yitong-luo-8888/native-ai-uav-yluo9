# HW6 Reflection — Human-on-the-Loop Mission Response Planner

> Draft. Sections 1 and 3 are drafted from the code and the test runs;
> sections 2 and 4 are mine to write (marked **TODO**).

## 1. Where the design helped, and where it got in the way

### Where it helped

- **Injecting every dependency made the hard parts testable without a drone.**
  `Planner` is built from a `Bus`, a `UavClient` per UAV, a `Clock`, a
  `DecisionSource` and a runner (`planner/main.py`). Unit tests swap in
  `FakeBus`, `FakeUavClient`, `FakeClock` and an inline runner, so the full
  event → request → decision → validation → execution loop runs synchronously.
  41 unit tests finish in under a second, including a 180 s decision timeout
  (`FakeClock.wait()` jumps time forward instead of sleeping).
- **The validator is its own stage, so it doesn't care who chose.**
  `Validator.validate()` runs after *any* `DecisionSource`. When the
  simulated battery drained to 14%, every response in the integration run was
  rejected with a reason ("UAV 1 battery 14% is below the 25% reserve plus
  5% hover_stream cost (30% needed)."), and nothing flew. The rule held under a condition I
  never set up on purpose (`evidence/integration-battery-14pct.txt`).
- **A tick-driven executor made cancel and resume simple.** `Executor`
  stores the waypoint index it was heading to (`ActiveResponse.resume_index`)
  in `submit()`, *before* leaving the route. Every way out (COMPLETED,
  FAILED, CANCELLED) goes through `_finish()`, which restores that index.
  Cancel is just a flag checked on the next tick, so it works mid-step without
  threads fighting over the vehicle.
- **The person registry owns the "ask once" rule.** `claim_for_decision()`
  checks and sets PENDING under one lock, so two near-simultaneous sightings
  can't both open a popup. The decision status (UNDECIDED / PENDING /
  RESPONDED / DISMISSED) is the only thing that decides whether to ask again.
- **Matching the popup's payload keys exactly meant the popup needed no
  changes.** `hotl_popup.py` is untouched.

### Where it got in the way

- **The popup contract has no structured route-progress field.** The
  dashboard runs as a separate process and can only see MQTT. It reads the
  current and resume waypoints by parsing `behavior_status.detail` text
  ("heading to waypoint 4 of 10", "will resume at waypoint 4 of 10"). That
  works, but a wording change in `executor.py` would silently break the map.
  I chose this over inventing a payload field.
- **"Simulate Timeout" doesn't fit the contract.** A real timeout is the
  *absence* of a message, which the dashboard can't send. It sends
  `{"request_id": ..., "action": null}`, which `HumanDecisionSource`
  treats as "no answer". It reuses an existing key with a null value, but it's
  still a convention the popup never uses.
- **There's no release command.** `deliver` has to simulate the drop in the
  planner: it removes the item from the world model and publishes
  "payload released: <item>". The flight looks right, but nothing physical
  confirms the release.
- **Shared MQTT connections duplicated messages.** In the first
  integration run, the test and the planner shared one connection. The
  overlapping subscriptions (`mission/#` and `mission/events`) made the broker
  deliver each event twice. It was harmless only because the registry merged
  the copy. I fixed it in two places: the planner now ignores an `event_id` it
  has already seen (QoS 1 is at-least-once anyway), and the test uses its own
  connection, like the separate processes in real use.
- **Integration tests are timing-sensitive.** The stretch cancel test once
  failed because the UAV reached a waypoint between the test capturing "index
  before" and the planner capturing it. The fix was in the test (inject only
  while the UAV is mid-leg, at least 15 m from its next waypoint), not the
  planner. But it shows how easily "same waypoint" assertions race against a
  moving vehicle.
- **One response per UAV at a time.** A busy UAV makes the validator reject
  any new response for it ("already executing … cancel it first"). That's
  honest, but the operator has to wait out the re-asks or dismiss. There's no
  queue. (Multi-UAV response was out of scope.)

## 2. What surprised me when it flew

**TODO (mine to write).** Guiding questions:

1. The simulated battery went from 100% to 14% over roughly ten minutes of
   test flights, then read 0.0 while the UAV kept hovering at 20 m with its
   voltage unchanged and no failsafe. What did that change about how much you
   trust `battery_level` as the validator's input?
2. Compare the first integration run with the fakes. What did the real
   vehicle do (takeoff delay, arrival tolerance, time to descend to 5 m) that
   the fake UAV's instant "teleport" hid?
3. The stretch cancel test raced against the UAV reaching a waypoint. Did
   that change what you think "resume at the same waypoint" should mean, or
   how you'd test it?
4. When you watched the popup and dashboard during a live response, was the
   status detail (PENDING → RUNNING step labels → COMPLETED) enough to know
   what the UAV was doing, or did you find yourself looking at the map?

## 3. What I'd change before an AI starts making the decisions

The seam already exists. `AIDecisionSource` implements
`DecisionSource.decide(DecisionRequest) -> action | DISMISS | None` and gets
exactly what the popup gets: the event, world_state, the candidate menu,
previous_rejection and timeout_s. Swapping it in is one argument to
`build_planner()`, and every choice it makes still goes through the
`Validator`. These are the things I'd change before trusting it.

1. **Enforce menu membership in the validator.** Right now the validator
   checks feasibility (item on board, battery, a busy UAV, sane parameters)
   and re-checks the R2 rule for `deliver`. It doesn't check that the chosen
   response type and UAV were actually in that request's menu
   (`eligible_uavs`). A human can only click what's shown; an AI can return
   anything. The validator should reject off-menu choices against the
   candidates that were offered.
2. **Bound the parameters, not just their sign.** A human gets spin boxes;
   an AI could ask for `duration_s = 9000` or `delivery_alt_m = 0.5`. Today
   the validator only rejects non-numeric, negative or zero values. It needs
   upper and lower limits from config (minimum safe delivery altitude, maximum
   hover time per battery cost).
3. **Make battery cost depend on the response.** The cost is a flat number
   per response type from `mission_config.json`. A 10-minute hover costs the
   same 5% as a 10-second one, and distance to the target is ignored. With a
   human that's tolerable. An AI optimising against the validator would learn
   to pick long, far responses that are "free".
4. **Rate-limit re-asks after rejection.** A rejected choice is re-asked
   straight away with the reasons. A human reads them and changes course; an
   AI that keeps choosing the same thing would loop as fast as the validator
   answers. The decision loop needs a cap on attempts (then mark the person
   UNDECIDED and say so).
5. **Revisit the R2 threshold for an AI.** 0.35 sits just above the one
   false positive (0.31) and the one real hit (0.26) from the class frames.
   That's two data points. With a human, a low-confidence person still gets
   a verify-only response and a human looks at the stream. An AI would be
   reading the same confidence number the threshold was guessed from. Before
   handing over, I'd collect more labelled detector output and pick the
   threshold from it, and I'd consider requiring a completed verify response
   (hover or circle) before `deliver` is even offered to an AI.
6. **Log decisions for audit.** Every decision request, choice, verdict
   and outcome is already on MQTT. For an AI, I'd also record *why* it chose
   (its rationale) next to the `action_result`, so a human reviewing after the
   fact can tell a bad choice from a bad menu.
7. **Keep a human veto.** The popup's Cancel already stops a running
   response and resumes the route. With an AI deciding, that becomes the main
   human control, so I'd make sure the dashboard keeps showing every
   AI-approved response the moment it's approved, not only once it's RUNNING.

## 4. Lessons Learned about using Claude


Insisting that Claude "stop and tell me if it doesn't exist" caught the wrong guide path in the first minutes rather than after hours of work. It cost about ten minutes of back-and-forth, but it saved me from building tests against the wrong conventions. The thing Claude flagged that I would not have caught myself was the stretched-test marker running under the default unit command — silently running SITL-dependent tests when I thought I was running fast unit tests. The SITL battery drain I would have noticed, but only after a confusing failure. The duplicate MQTT deliveries I would have missed entirely and written off as flakiness.

I had to correct Claude twice in ways that mattered: tell it not to read drone_backend.py when it went looking for command primitives that weren't in ARCHITECTURE.md, and tell it not to probe Windows for Docker when the stack runs from WSL. Both corrections made the result better, not just slower — reading the backend would have produced primitives inferred from a source file instead of the documented interface, and probing the host would have burned time on the wrong environment.

.claude/skills/project-test-guide didn't end up driving much of the workflow, because the file wasn't in the place I initially pointed Claude at. That itself is the lesson: I should have verified the path before launching. For next week's AI decision-maker, I'd write the guide to say explicitly where each artifact lives, which files are read-only, and what to do when a path in the prompt doesn't exist — because the biggest cost this week wasn't a bad decision, it was a missing instruction.
