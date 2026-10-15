# HW7 — Understanding the pipeline

Answer each question in 2–5 sentences, in your own words, from your own `hw07/clues/` code.
Name the file (and line) you are describing. Understanding and explaining matter more than length.
One of these questions will be drawn from a hat during your presentation
on Oct. 15, and you will answer it live.

## Data and structure

### Q1. Data in, data out

What is a `Candidate`, and what is a `ClueAssessment`? Where does each come from, and where does each go (name the file or MQTT topic)?

**Answer:**
A `Candidate` (`lab/lesson7/contract.py`) is one object Stage 1 flagged: its lat/lon, the detector's label and confidence, the crop as a base64 PNG, the crop's ground scale, and whether it is a zoomed view. `detector.py` builds it from camera frames in flight; offline, `scenario.py`'s `Scenario.candidate()` builds it for `evaluate.py`. Either one hands it to my `ClueAnalyzer.analyze()` (`hw07/clues/pipeline.py:40`). A `ClueAssessment` is what `analyze()` returns (`pipeline.py:80`): the candidate without images, every description, the relevance and decision dicts, the code-set `search_center` and every `StageCall`. `detector.py` publishes it on `mission/clues` (QoS 1), where my planner's `ClueHookup` (`hw06/planner/clue_hookup.py:58`) receives it. `evaluate.py` instead scores it and appends it to `hw07/clues/data/eval_runs.jsonl`.

### Q2. Stages and their specs

Where is each stage defined in your code, and what does its `StageSpec` hold? If you renamed a stage, which files would change?

**Answer:**
Each stage is declared once in `hw07/clues/stages.py:25-27` (`DESCRIBE`, `RELEVANCE`, `DECIDE`), and each has one function in the same file: `describe` (line 56), `assess_relevance` (line 70) and `decide_action` (line 79). A `StageSpec` holds the stage's name (which is also its prompt file, `prompts/<name>.md`), its pydantic answer schema from `messages.py`, and its effort. The backend, `TracingBackend` and `FakeBackend` all read the spec, so none of them spell a stage name. Renaming a stage means changing the name string in `stages.py` and renaming its file in `prompts/`. Nothing else changes, because my tests key `FakeBackend` by the spec object, not the name.

### Q3. What each stage sees

For each of your three stages, list what goes into the request (images, text). Why must Describe never see the missing person's description?

**Answer:**
Describe (`stages.py:56`) gets the crop image plus one text block: normal or zoomed view, and the ground scale in cm per pixel. Relevance (`stages.py:70`) gets text only: the person's name, age, summary, clothing, belongings, other details, last-seen and conditions, plus Describe's last answer as JSON. Decide (`stages.py:79`) gets text only: the person's name and last-seen, the object type and Describe's confidence, the distance from the last known point (computed by code), whether a closer look was already taken, and Relevance's full answer. Describe must stay blind to the mission because a describer told "we're looking for a brown teddy bear" tends to see one. Its description then confirms the hypothesis instead of testing it, and Relevance's comparison means nothing.

### Q4. Schemas

What does "schema" mean for a stage, and what is a Pydantic class? What happens in your code if the model returns `relevance = "maybe"`?

**Answer:**
A stage's schema is the exact shape its answer must have: which fields, their types, the allowed values, and the order they're written in. It is sent to the API as the structured-output format (`output_format=spec.schema`, `llm.py:63`). A Pydantic class (e.g. `Relevance` in `messages.py:45`) is a Python class whose typed fields are both the JSON schema and the validator, so the data can't be built unless it fits. `relevance` is `Literal["high", "medium", "low", "none"]`, so structured output constrains the model to those values. If `"maybe"` came back anyway, parsing raises a `ValidationError`, which `llm.py:68` catches as "invalid output". The backend retries once, then raises `LLMError`. My pipeline doesn't catch that, so no assessment is published for that object.

### Q5. The contract

What does `contract.py` fix that you may not change, and why does it exist? Which of its classes does your code create, and which does it only receive?

**Answer:**
`lab/lesson7/contract.py` fixes the interface between the given tools and my pipeline. It defines `Candidate` in and `ClueAssessment` out, the action menu `ACTIONS`, `RELEVANCE_LEVELS`, the effort levels, `StageSpec`, `StageCall`, and the rule that a converge needs a radius and a `search_center`. It exists so that `evaluate.py`, `detector.py`, `inject_clue.py` and my planner can all work with any student's pipeline, and its validator enforces the action menu no matter what my prompts say. My code creates `StageSpec` (`stages.py:25`), `ClueAssessment` and `LatLon` (`pipeline.py:76-80`), and my backend creates `StageCall` (`llm.py:84`). It only receives `Candidate` and `MissionContext` from the tools.

## Calling Claude

### Q6. One call, end to end

Trace one Describe call from `evaluate.py` to `client.beta.messages.parse(...)`, listing each function and its file. Where are the prompt and the effort chosen?

**Answer:**
`evaluate.py:main()` builds `ClaudeBackend()` (line 78), wraps it in `TracingBackend` (line 101) and calls `analyzer.analyze(candidate)` (line 109). In `pipeline.py:63`, `analyze()` calls `run(describe, candidate)`, which calls `stages.describe(backend, candidate)` (`stages.py:56`). That builds the image and text blocks and calls `backend.generate(DESCRIBE, load_prompt(DESCRIBE), content)` (line 67). `TracingBackend.generate()` (`llm_tools.py`) prints the request and calls `ClaudeBackend.generate()` (`hw07/clues/llm.py`), which calls `self.client.beta.messages.parse(...)` at line 58. The prompt is chosen by `load_prompt(spec)`, which reads `prompts/describe.md` because the spec's name is `"describe"`. The effort comes from the spec too (`effort="medium"` at `stages.py:25`), sent as `output_config={"effort": spec.effort}` (`llm.py:64`; not sent to `claude-haiku-4-5`, which rejects it).

### Q7. System prompt and user message

In your requests, what goes in the system prompt and what goes in the user message? Why is that split useful?

**Answer:**
The system prompt (`prompts/<stage>.md`) holds what stays the same for every call: the stage's role, the rules (e.g. the relevance levels and what counts as a hard mismatch, or Decide's policy table), and how to fill each field. The user message holds only this call's facts: the crop and scale for Describe, the person and the description for Relevance, the relevance answer and distance for Decide (`stages.py:56-90`). The split keeps instructions and data apart. I can change a rule in one file and compare runs, the trace shows exactly what data each call got, and the facts can't quietly rewrite the instructions.

### Q8. Effort, cost and the key

What does effort control, which effort did you give each stage, and why? How is the cost of a call calculated? Where does your code get the API key, and how do you make sure it is never committed?

**Answer:**
Effort controls how much the model thinks (and how many tokens it spends) before answering. I gave Describe `medium`, because every later stage relies on it and reading a ~20-pixel object takes care. Relevance gets `medium`, because the near-miss decoys test exactly its judgement. Decide gets `low`, because with my policy it's nearly a table lookup and more thinking only gives it room to argue past the policy (`stages.py:25-27`). Cost is `cost_usd(model, in, out)` in `llm_tools.py`: input tokens × input price plus output tokens × output price, per million, from `PRICES`, summed over both attempts (`llm.py:86`). The key comes from `load_api_key()` (`llm.py:44`): the `ANTHROPIC_API_KEY` environment variable, else the repo-root `.env`, which `.gitignore` excludes. Before pushing I run `git diff --cached | grep -i sk-ant`, and it prints nothing.

### Q9. When a call fails

Walk through what your code does if Claude refuses, cuts off, or returns an answer that doesn't fit the schema. What does the planner receive in each case?

**Answer:**
`ClaudeBackend.generate()` (`hw07/clues/llm.py:56-88`) checks why the response stopped before trusting it. `stop_reason == "refusal"` sets problem "model declined" (line 77), `"max_tokens"` sets "cut off" (line 79), and a missing `parsed_output` or a parse-time `ValidationError` sets "no parsable output" or "invalid output" (lines 68, 81). In each case the loop retries once. If the second attempt fails too, it raises `LLMError` (line 88), and an API HTTP error raises `LLMError` immediately (line 74). My `ClueAnalyzer` doesn't catch `LLMError`, so `detector.py`'s worker logs "Clue analysis failed" and publishes nothing. The planner receives no message for that object, rather than a half-made or default answer it might act on.

## Control and safety

### Q10. The closer look

What two things can trigger a closer look? What stops it from happening twice? What happens in flight, where `closer_look` is `None`?

**Answer:**
Describe answering `needs_closer_look = true` (`pipeline.py:64`), or Decide choosing `inspect_closer` (`pipeline.py:69`), which then re-runs Relevance and Decide on the zoomed description. Both go through `look_closer()` (`pipeline.py:50`), which sets the single `looked_closer` flag, and it returns `None` if the flag is already set, so a second request does nothing. A candidate that arrives already zoomed starts with the flag set (line 43). If Decide still says `inspect_closer` after the look, `_constrain` (`pipeline.py:98`) downgrades it to `log_only`. In flight `closer_look` is `None`, so `look_closer()` returns `None` and an `inspect_closer` decision is published as is. My planner turns it into a `hover_stream` over the clue (`hw06/planner/clue_hookup.py:87`).

### Q11. The model's authority

Which decisions does the model make, and which does your code make? Why does the converge-search centre come from code, and what can your validator still reject?

**Answer:**
The model decides what the object is, how relevant it is, which menu action to propose, the search radius and the priority. My code decides everything else. `_constrain` (`pipeline.py:90`) downgrades a converge on low/none relevance or a second `inspect_closer`, and clamps the radius to 20–200 m. The `search_center` comes from the candidate's position (`pipeline.py:76`), and in the planner the UAV, the target, the flight pattern and whether anything flies are all code. The centre comes from code because the model never sees coordinates and can't measure them: a model-written position could be invented or mistyped and send a UAV to the wrong place, while the candidate's position comes from geolocation. My validator (`hw06/planner/validator.py`) can still reject a missing or non-numeric centre or radius, an unowned UAV, a battery below reserve plus the circle/hover cost, or a UAV already busy with another response. It also clamps the circle radius to 10–40 m.

### Q12. Prompts versus code

You want Relevance to also consider the clue's distance from the last known point. Is that a prompt change, a code change, or both? Which files?

**Answer:**
Both. The model can't compute a distance it isn't given, so code has to calculate it and put it in Relevance's request: `assess_relevance()` in `stages.py:70` would call `distance_m(lkp, candidate)`, as `decide_action()` already does at line 82, and add it as a text line. Then `prompts/relevance.md` needs a rule for how distance should weigh in (e.g. far beyond walking range lowers relevance a step). If I wanted the answer recorded, I'd add a field to `Relevance` in `messages.py`.

## Testing and evaluation

### Q13. Testing without Claude

How does `FakeBackend` let you test a stage without an API key? Name one thing your unit tests can prove and one thing only `evaluate.py` can show.

**Answer:**
`FakeBackend` (`lab/lesson7/llm_tools.py`) has the same `generate(spec, system, content)` method as `ClaudeBackend`, but returns scripted answers per spec (validated against my schemas) and records every request in `.requests`. So my tests can inspect exactly what each stage sent and drive the pipeline down any branch. My unit tests (`hw07/clues/tests/test_pipeline.py`) prove that the closer look happens at most once even if Describe and Decide keep asking for one, which is a property of my code. Only `evaluate.py` can show whether the real model actually identifies a navy cap as Ethan's and a beanie as not, and how often it agrees with itself.

### Q14. Measuring

How does `evaluate.py` decide whether a clue was handled correctly? Why run each clue three times, and what would 60% agreement tell you?

**Answer:**
`evaluate.py` scores two things per run against the clue's `truth` in `scenario.json`. Relevance is correct when `high`/`medium` matches `truth.relevant` (`judged_relevant`, line 44), and the action is correct when `decision["action"]` is in `truth.acceptable_actions` (line 121). The model is not deterministic: one correct run could be luck. With `--repeat 3` the share of runs that picked the clue's most common action (line 144) measures consistency. 60% agreement would mean that for a typical clue the pipeline picks different actions on different runs of the same input, so its answer is close to a coin flip and a single in-flight call can't be trusted. I'd look for the stage whose answer varies (usually Describe on an unclear crop, or a relevance level right on a boundary) and tighten that prompt or schema.

## Running end to end (Part 2)

### Q15. The running system

List every process that must be running for your end-to-end demo in new-gui and what each one does. Which MQTT topics connect them?

**Answer:**
(1) The `lab/` docker stack (`docker compose up -d`): the Mosquitto broker plus ArduPilot SITL drones and the drone backend, which turns `uav/<id>/command` into MAVLink and publishes `uav/<id>/telemetry`. (2) new-gui with camera simulation on and my scene toggled on (written by `scenario_to_scene.py`), publishing `VIDEO_STREAM/<color>/frame`. (3) `lab/lesson7/detector.py <my set> --oracle`, which reads the frames, crops each clue, runs my `ClueAnalyzer` and publishes `ClueAssessment`s on `mission/clues`. (4) My HW6 planner (`python -m planner.main` in `hw06/`), which flies the route via `uav/1/command`. Its `ClueHookup` subscribes to `mission/clues`, validates each proposal and reports on `mission/action_result`, and its executor reports progress on `mission/behavior_status`. Optionally (5) my HW6 dashboard and `mosquitto_sub -t 'mission/#'` to watch those topics.
