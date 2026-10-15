# HW7 design — clue-reasoning pipeline

Written before the code, then kept in step with it. Section 5 lists where the
code ended up different from the first draft, and why.

```
Candidate ─► describe ─► (closer look?) ─► relevance ─► decide ─► code guard ─► ClueAssessment ─► mission/clues
             pixels only    zoom ×6, once    text only     text only   menu/radius/centre
```

Code: `hw07/clues/` — `messages.py` (schemas), `stages.py` (StageSpecs and one
function per stage), `prompts/*.md` (one system prompt per stage),
`pipeline.py` (`ClueAnalyzer`), `llm.py` (given backend, unchanged).

## 1. Stage contracts

General rules:

- **The system prompt holds the job, the rules and the output conventions. The
  user message holds the facts for this one call** (image, scale, mission
  facts, earlier stage outputs). The system prompt is the same for every
  call, so a prompt change is a single-file diff and can be compared across
  runs.
- **Fields are ordered evidence first, verdict last.** The model writes fields
  in schema order, so it describes what it sees before it names the object,
  and lists matches and mismatches before it picks a relevance level.
- **Each later stage gets text, not pixels.** Describe is the only stage that
  sees the image. If Relevance is wrong, the trace shows whether it was given
  a wrong description (Describe's fault) or read a correct one badly (its own
  fault). That is what R6's "first wrong stage" needs.

### Stage 2 — Describe (`DESCRIBE = StageSpec("describe", Description, effort="medium")`)

**Sees:** the crop (PNG), the ground scale of the crop (`ground_m_per_px`,
already life-size), the crop's size in pixels, and whether this is the
zoomed closer-look view.

**Deliberately not shown:** anything about the mission: no person, no
clothing list, no last-seen text, no search area. It also doesn't get the
Stage-1 `cv_label` (`"unknown"` under `--oracle`; under YOLOE a generic word
that could anchor it) or the candidate's coordinates. A describer that knows
we're looking for a teddy bear tends to see a teddy bear. Its job is to say
what is there, so that Relevance's comparison means something.

**Schema `Description`** (field order = order written):

| Field | Type | Meaning |
|---|---|---|
| `observations` | str | What is visible before naming anything: shapes, colours, markings, texture, what's around it. Forces looking before labelling. |
| `object_type` | str | Best short name for the object ("child's baseball cap"). `evaluate.py` prints it. |
| `category` | Literal: clothing, footwear, headwear, bag, toy, sports_equipment, personal_item, litter_or_debris, natural, other, unknown | Coarse kind, so Relevance can match on kind even when the name differs. |
| `colors` | list[str] | Main colours, most prominent first. |
| `distinctive_features` | list[str] | Logos, patches, bows, buttons, laces, patterns: the things that tie an item to one person. |
| `estimated_size_cm` | float or null | Longest dimension, from pixels × ground scale. Null if it can't be measured. |
| `wearer_size` | Literal: child, adult, any, not_applicable, unknown | For clothing, shoes and bags: who it would fit. This catches the "right colour, wrong size" near miss. |
| `confidence` | Literal: high, medium, low | How sure it is of `object_type`. |
| `needs_closer_look` | bool | True when it can't tell what the object is, or can't see a detail (colour of a small part, a patch) that would change the identification. |

**Effort `medium`.** This is the stage the other two depend on, and reading a
20-pixel icon well takes some thought. `high` was not worth the cost: when
the object can't be read, the closer look fixes it, not more thinking.

### Stage 3 — Relevance (`RELEVANCE = StageSpec("relevance", Relevance, effort="medium")`)

**Sees (text only):** the person (name, age, summary, clothing, belongings,
other details), when and where they were last seen, the conditions, and
Describe's last description as JSON (the zoomed one, if a closer look was taken).

**Deliberately not shown:** the image. Relevance compares a description with
a person. Giving it the pixels as well would let it reinterpret them to fit
the person, and it would blur which stage made a mistake. Coordinates aren't
shown either: distance from the last known point is a decision question
(see Decide), not an identification one.

**Schema `Relevance`:**

| Field | Type | Meaning |
|---|---|---|
| `possible_items` | list[str] | Every listed item the object is consistent with (kind, or colour + size + outline when the kind is unclear). Added by the R6 fix, see Section 5. |
| `candidate_item` | str or null | The best of `possible_items`, or null. |
| `matches` | list[str] | Specific attributes that agree (kind, colour, feature, size). |
| `mismatches` | list[str] | Specific attributes that contradict. One hard mismatch (wrong kind, wrong colour, adult size for a child's item) rules a match out. |
| `rationale` | str | One or two sentences tying matches and mismatches to the verdict. |
| `relevance` | high / medium / low / none | Contract field. **high**: matches a listed item on kind *and* a distinctive colour or feature, no hard mismatch. **medium**: plausibly the item (kind matches) but a key detail is unclear. **low**: generically the kind of thing a child might have, but not a listed item, or a hard mismatch. **none**: nothing to do with the person. |

**Effort `medium`.** This is the judgement the whole pipeline exists for, and
the near-miss decoys are built to catch a careless match. It is text in, so
`medium` costs little.

### Stage 4 — Decide (`DECIDE = StageSpec("decide", ClueDecision, effort="low")`)

**Sees (text only):** Relevance's whole answer, the description's
`object_type`/`confidence`/`needs_closer_look`, the person's name and last-seen
text, the clue's **distance from the last known point in metres (computed by
code)**, whether a closer look has already been taken, and the action menu
with the policy.

**Deliberately not shown:** coordinates of any kind. The model cannot write a
position because it never sees one, and the schema has no field for one.

**Schema `ClueDecision`:**

| Field | Type | Meaning |
|---|---|---|
| `rationale` | str | Why this action, first, so the action follows from the reasoning. |
| `action` | ignore / log_only / inspect_closer / converge_search | Contract field. |
| `search_radius_m` | float or null | Contract field: required for converge_search, null otherwise. The prompt asks for 30–150 m. |
| `priority` | high / medium / low or null | For converge_search: how urgent (the planner logs it). |

**Effort `low`.** The policy below is nearly a table lookup on relevance.
More thinking here would only give the model room to argue its way past the
policy.

## 2. Decision policy

| Relevance (after any closer look) | Action | Why |
|---|---|---|
| high | `converge_search`, radius 30–150 m (smaller when the clue is near the last known point, larger when it's far or the clue could have been carried) | Strong, specific evidence of where the person was. |
| medium, no closer look yet | `inspect_closer` | A zoomed look is cheap and usually settles it. |
| medium, already looked closer | `log_only` | Still unsure after the best view we can get: flag it for the operator, don't move the search. |
| low | `log_only` | Might matter later (e.g. if a second clue turns up nearby). |
| none | `ignore` | Not evidence of this person. |

**Why converge_search should be rare.** A converge pulls a UAV off its search
route to circle one spot. That costs battery and leaves the rest of the area
unsearched. A false converge (on a stranger's cap or a doll) pulls the search
to the wrong place: in a real search that costs time the child doesn't have.
Litter at a game-day site is everywhere, so a policy that converges on
"maybe" would spend the mission chasing it. Only `high` (kind *and*
distinctive detail match) earns a converge.

**Code guard (`pipeline.py`, `_constrain`), applied after Decide, before the
assessment is built.** The model proposes. These rules are not negotiable:

1. `converge_search` with relevance `low`/`none` → `log_only`. A converge
   needs relevant evidence.
2. `inspect_closer` after the closer look was already taken → `log_only`
   (no second look, and no `inspect_closer` from offline runs that already zoomed).
3. `converge_search` with a missing radius → 80 m. A radius outside 20–200 m is clamped
   into that range. (The planner's validator clamps again to what the UAV can fly.)
4. `search_center` = the candidate's `lat`/`lon`, set in code, only for a
   converge. Anything else has `search_center = None` and `search_radius_m = None`.

Every override is reported through `on_event` and recorded in the decision
dict (`guard` field), so the trace shows when the code overrode the model.

**Closer look (R4).** Triggered by (a) Describe saying `needs_closer_look`,
or (b) Decide choosing `inspect_closer`. Either way:
`closer_look(candidate)` → describe the zoomed view → (re-)run Relevance and
Decide on it. A single `looked_closer` flag in `analyze()` allows it at most
once per call, and a candidate that already arrives `zoomed=True` never gets
another. In flight `closer_look` is `None`: a Describe "needs closer look" just
goes on to Relevance, and an `inspect_closer` from Decide is published as is.
The planner turns it into a `hover_stream` over the clue.

**Failure.** The backend raises `LLMError` after its one retry. The pipeline
does not catch it: there is no honest assessment to publish, so
`evaluate.py` records a FAILED run and `detector.py` logs it and publishes
nothing. The planner never acts on a made-up answer.

## 3. Test set — `hw07/scenarios/lost-boy-north-gate/`

**Who:** Ethan, 8 (GUI image `people/boy-greenshirt.png`).

**Description as last seen (written before drawing any clue):**
"8-year-old boy, slim, short brown hair. Navy-blue baseball cap with a grey
front panel, worn backwards; green short-sleeved t-shirt; blue denim shorts;
black rubber wristband on his left wrist; white sneakers. Carrying a small
orange backpack with a green dinosaur patch on the front pocket. Last seen
45 minutes ago near the stadium's north gate, heading for the restrooms,
with his backpack on."

**Placement:** all six clues lie inside UAV 1's HW6 search route north of
the stadium (lat 41.6990–41.6998, lon −86.2378 to −86.2363), at least 15 m
apart, so `detector.py --oracle` sees each one on the normal sweep. The
search altitude is 20 m, the route altitude. Last known point: the north gate, just west of the route.

| Id | Clue | Truth | Acceptable | Why it's in the set |
|---|---|---|---|---|
| e01 | navy cap with grey front panel (child size) | relevant | converge_search | His cap. Tests a match that depends on colour (navy) plus a distinctive detail (grey front). |
| e02 | small orange backpack, green dinosaur patch | relevant | converge_search | His backpack. Distinctive patch, a belonging he was carrying. |
| e03 | navy knit beanie with pompom | decoy (**near miss**) | ignore, log_only | Right colour, right body part, wrong kind (beanie, not a cap). Catches a Relevance that matches on colour plus "headwear" alone. |
| e04 | man's brown oxford shoe (shared) | decoy | ignore, log_only | Adult footwear: tests `wearer_size` vs. an 8-year-old's white sneakers. |
| e05 | doll in pink dress (shared) | decoy | ignore, log_only | A child's toy that isn't his: "a child was here" is not "Ethan was here". |
| e06 | soccer ball (shared) | decoy | ignore, log_only | Boy + stadium makes a ball tempting, but nothing in the description mentions one. |

Cap, backpack and beanie are drawn with `icon_kit.py` by
`hw07/scenarios/lost-boy-north-gate/make_icons.py`, at the people scale and placed at
`width_m` 8 like the people icons (`scene_scale` 9).

## 4. Part 2 — planner hookup (R7)

`hw06/planner/clue_hookup.py` subscribes to `mission/clues` (QoS 1). For each
`ClueAssessment` it:

1. drops duplicates (same `assessment_id`: QoS 1 can deliver twice);
2. maps the proposal: `inspect_closer` → `hover_stream` over the candidate
   position (standoff 0); `converge_search` → `circle_stream` around
   `search_center` with `radius_m = search_radius_m`; `ignore`/`log_only` →
   logged, nothing flies;
3. marks the action `decided_by: "ai"` (plus `assessment_id`, object, relevance),
   picks the UAV (the reporting UAV if this planner owns it and it's idle,
   else the idle one with the most battery);
4. runs the **same `Validator`** as operator decisions. For `circle_stream`
   the validator now clamps the radius to `[min_circle_radius_m,
   max_circle_radius_m]` (10–40 m, so a circle fits the 20 m-altitude route
   area) and says so in a note. It still rejects on battery, a busy UAV,
   missing or non-numeric target, and so on;
5. publishes the verdict on `mission/action_result` (with `decided_by: "ai"`
   and any notes) and, if approved, hands it to the same `Executor`.

## 5. Changes from the first draft

(Kept up to date during the build. See `report.md` for the traced failure fix.)

- *First draft:* Relevance also saw the crop. *Changed before coding:* text
  only, so that a wrong answer can be traced to one stage (Section 1).
- **Relevance schema: `possible_items` added before `candidate_item`** (R6
  traced failure, `report.md` §5). With one `candidate_item` field, the model
  committed to the first plausible item ("blue denim shorts") and argued only
  against that, while Ethan's cap was the better match. Listing every possible item
  first makes it compare them before it chooses.
- **Relevance prompt: rule for unclear descriptions** (same fix). When Describe says
  `confidence: low` / `category: unknown` / `needs_closer_look`, colours,
  markings, size **and outline** all consistent with a listed item → `medium`
  (→ `inspect_closer`), not `low`. The outline clause came from the first full
  GUI run: without it, an unclear white blob (the soccer ball) became
  "consistent with white sneakers" on colour and size alone.
- **Decision policy in flight.** In-flight crops are much blurrier than
  `evaluate.py`'s renders, so in flight the typical answer for the person's own
  item is `medium` → `inspect_closer` → hover. A converge only follows once a
  view is clear enough for `high`. That is the intended rarity of converges.
- **Planner same-spot rule** (`hw06/planner/clue_hookup.py`). The given detector
  re-reports a clue while a UAV hovers right over it. A repeat of an
  already-approved response type within 5 m is rejected with a reason. An
  escalation (hover, then converge) is still allowed.
- **`llm.py`: effort not sent to `claude-haiku-4-5`**, which answers 400 "does
  not support the effort parameter". This is the only change to the given backend.
  Per-stage effort applies to the default model, `claude-sonnet-5-5`.
