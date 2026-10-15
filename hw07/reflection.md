# HW7 reflection — an LLM clue-reasoning pipeline

> Drafted from what happened during the build and the runs (`report.md` has
> the evidence). It's my reflection to own, so edit anything that doesn't sound like me.

## Where the model surprised me

- **Describe was more honest than I expected.** On a blurry 20-pixel
  in-flight crop of Ethan's cap it didn't make up a label. It said "blurry,
  roughly rectangular blue object … large white-grey oval patch",
  `confidence: low`, `needs_closer_look: true`. I expected the vision stage to
  be the weak link, but it was the most calibrated stage in the pipeline.
- **The judgement stage threw that honesty away.** Relevance read "I can't
  tell" as evidence *against* and filed Ethan's own cap as `low`. It even wrote,
  in its own rationale, that the navy cap "is a possible alternative". The model
  noticed the right answer and still chose the wrong one. The cause was the
  schema: a single `candidate_item` field written first made it commit to
  "blue denim shorts" before comparing anything. **Field order changes how the
  model reasons, not just how its answer is laid out.** That was the most
  useful thing I learned this week.
- **Fixes have side effects.** My first fix ("unclear plus consistent colour and size
  → `medium`") turned the soccer ball into a possible white sneaker. Again, its
  rationale said "the flower-like lobed shape is odd" and still didn't count it
  as a mismatch. Adding *outline* to the rule fixed it. Each prompt change needed
  a re-run of the whole test set, not just the clue I was fixing.
- **Offline 100% hid the real problem.** Both test sets scored 100% offline with
  93% agreement, while in flight the same pipeline sent Ethan's cap to
  `log_only`. The offline renders are much sharper than what the GUI camera
  gives. If I had only trusted `evaluate.py`, I would have shipped the bug.
- **Consistency was good but not perfect.** On three identical runs, Lily's
  shoe went `log_only`, `log_only`, `ignore`. Both are acceptable, but a 7%
  disagreement on an easy decoy tells me any single in-flight answer is a sample, not a fact.

## What I would never let it decide

- **Where anything flies.** The model never sees a coordinate, and there is no
  coordinate field in any schema. The search centre is the candidate's position,
  set in `pipeline.py`. The model writes a radius, and my code clamps it
  (20–200 m), and then the planner's validator clamps the orbit again (10–40 m).
- **Whether a proposal is feasible.** Battery reserve, a busy UAV, and a repeat
  over the same spot are all code. In the simulator the validator rejected two
  high-relevance AI converge proposals at 26% battery, and that was exactly right.
- **Whether it gets another look.** The closer-look limit (once) is a flag in
  code, not an instruction in a prompt, so the pipeline always ends.
- **Delivering anything.** The AI's menu has no `deliver`. A payload drop onto
  a person on the strength of a blurry crop is not a model decision.
- **Silently moving the search.** In flight, my pipeline never escalated to
  `converge_search`, because no view was clear enough for `high`. I'd rather the
  AI under-converge and a human escalate than the reverse.

## Lessons learned about using Claude to build it

- **Claude was fast at the parts with a clear contract.** The schemas, stages,
  the three FakeBackend tests and the planner hookup came quickly, because
  `contract.py`, `StageSpec` and my HW6 `Validator` pinned down the interfaces. The
  more precise the contract, the less I had to correct.
- **It needed real runs to find real problems.** Every important finding came
  from running things, not from reading code: Haiku rejecting the `effort`
  parameter (a 400 from the given backend), the SITL battery lasting about 5 minutes, the GUI
  only drawing a saved scene after a click, the detector re-reporting a clue
  while the drone hovers over it, and the blurry flight crops. Running the
  system early and saving logs as evidence paid off more than any review.
- **Ask it for traces, not conclusions.** "Find the first stage whose answer was
  wrong" only worked because `TracingBackend` printed every request and answer.
  The model's own rationale fields (`rationale`, `mismatches`) were the most
  useful debugging data. Asking each stage to explain itself is worth the tokens.
- **Watch what it automates.** Claude wrote a one-command launcher and a GUI
  wrapper that presses the camera button for me. That is very convenient, but the
  wrapper uses private attributes of the GUI, which I need to remember.
  Also, one shell edit that embedded report text in a quoted command broke its own
  quoting and tried to run words from the text as commands. Nothing was
  damaged, but it is a reminder to keep prose out of shell commands.
- **Keep the key out of the chat.** I pasted my API key into the conversation
  to get unblocked. It works, but it's now in a transcript, so I will rotate it.

## What I would improve in the code's organisation

- **The kit:** `detector.py` re-reports a clue while a UAV hovers over it (its
  tracker re-confirms), and each repeat is a full LLM call: 12 assessments for 6
  clues in my run. De-duplication belongs before the pipeline is called, not only
  in the planner. The given `llm.py` also always sends `effort`, so the
  homework's own advice ("use `claude-haiku-4-5` while you iterate") fails with a
  400 until you patch it.
- **The kit:** saved scenes load marked visible, but the GUI doesn't draw them
  until the Scene Builder is toggled. A small public "show scene" / "start
  camera" API (or command-line flags) on new-gui would make R7 scriptable
  without reaching into private attributes.
- **Mine:** `evaluate.py`'s renders should include a "flight blur" variant,
  so the offline test set catches what only the GUI showed me. And the hover
  should feed its zoomed frames back into the pipeline as a `zoomed=True`
  candidate, so in-flight evidence can actually escalate to a converge.
- **Mine:** `ClueHookup` reaches into `Planner._approve_lock`. The planner
  should expose one public `validate_and_submit(action, source)` used by both
  the operator path and the AI path, so there is only one way into execution.
