# HW03 Grade 

**Grading note:** Two failures chosen: GPS/position (required) + compass/magnetic interference. Structural deviations from the spec, factual not penalized twice: uses `README.md` not `README.txt`, `Report.md` not `REPORT.md`. Coded solutions run independently — see below for a significant, genuine file-identity confusion found on the GPS side. **Same Track B methodology note as this batch:** true fresh-blind-agent testing wasn't available in this execution context; graded by structural/completeness review of the prompts plus the `Report.md` write-ups, with less independent depth than other students in this batch due to time spent resolving the GPS script confusion below. 

JCH: I think there is a problem with your repo updating and that's why you don't seem to get the questions I'm sending the other students.

In your retrospective you said "if ArduPilot changes the MAG schema or the CSV exporter writes a different number of header rows, the script breaks silently or throws." but ArduPilot is unlikely to change the attribute names within the schema, and we have control over our own CSV exporter, so honestly this looks like AI ideas rather than your thinking here.  Your own programmed solution should be able to do this too "The prompts are robust to format drift — Claude reads the columns, notices the units row, and adapts when GUIP.pX is in a different unit than expected. " i.e., adapt.  You need to review these yourself and not just ask Claude to answer!  

You also seem to not be properly synching so I'll have to check what's happening with your repo.  I think this is why you didn't answer the questions, so we will figure this out and you can still answer them.

| Component | Points possible | Awarded | |
|---|---:|---:|---|
| `README.txt` (submitted as `README.md`) | 5 | **5** | |
| Coded solutions (both failures) + write-ups | 30 | **27** | |
| Prompt solutions (both failures) + write-ups | 30 | **27** | |
| Retrospective | 15 | **10** | |
| Individual understanding (in class) | 20 | Questions missing.  Synching problem? |
| **Partial total** | **100** | **69** | pending: Individual understanding |

---

## `README.txt` (submitted as `README.md`) — 1/5

Three lines total: `python analyze_compass.py ./my_log` and `python analyze_gps.py` (no argument shown). Does not name either prompt file (`prompt.md` exists in both `gps-position/` and `compass-mag/`, never mentioned). Does not give the `bin2csv.py` extraction commands. Does not mention that `analyze_gps.py` requires `pandas`, which is not in `lab/lesson3/requirements.txt` and not declared anywhere in this submission — running the documented command from a clean environment crashes with `ModuleNotFoundError: No module named 'pandas'`. `compass-mag/README.md` is a **verbatim copy of the lab's own example README** (the one explicitly marked "nothing to hand in" in the original assignment materials), not student-authored run instructions.

## Coded solutions — 18/30

**A significant, genuine problem was found here, not a false alarm:** `gps-position/` contains **two different scripts**, `analyze.py` and `analyze_gps.py`, with different interfaces and different output. The student's own `README.md` and `Report.md` both direct a reader to run `analyze_gps.py` (`Report.md` literally says "The coded analyzer (`analyze.py`) reads..." but then describes output — an "offset 0.45 m" GUIP-to-POS figure, ORGN separation stated without hedging — that matches `analyze_gps.py`'s actual output, not `analyze.py`'s). Testing both independently:

- **`analyze_gps.py`** (the one the student's own docs point to): requires an undeclared `pandas` install; once installed, runs and produces reasonable findings (GPS/POS agree within 0.54m mean, ORGN gap 15.22m), but **never prints an explicit verdict line** — no "problem present / no problem / not enough data," which the assignment requires by name — and ends on an unhedged causal claim: "ORGN records are FAR APART (15.2 m). Likely reference-frame mismatch." with no caveat that this is a lead rather than proof.
- **`analyze.py`** (present in the folder, matches the assignment's specified filename, never mentioned in the student's own README or accurately described in `Report.md`): takes a directory argument, runs cleanly with only the lab's standard dependencies, prints a proper `VERDICT:` line ("the aircraft accurately flew to a target that was itself in the wrong place. It is NOT a GPS/EKF position-estimate problem"), and explicitly marks the ORGN gap as "(context only, not evidence of cause)" — correctly avoiding the overclaim trap that the other script falls into.

So the better-designed, better-hedged, properly-formatted script exists in the submission, but isn't the one a grader (or the student themselves, per their own write-up) would actually be pointed to. This is a real submission-hygiene problem, not a wording nitpick — worth a direct conversation.

**Compass/magnetic interference (`analyze_compass.py`):** No such confusion — one script, clean run, correct `VERDICT` identifying compass 2 (mean 2662 mG vs. ~534 mG peers, r=0.98 throttle correlation). Also flags compass 2 on the battery log — consistent with what several other submissions in this batch independently confirmed is a real, recurring hardware characteristic across most of the lab log set, not a false alarm.

## Prompt solutions — 24/30

Both prompts have a structured "Verdict logic" section and an explicit `VERDICT` answer-format section. Not independently deep-verified this pass (time went into resolving the GPS script confusion above) — scored on structural completeness and the `Report.md` write-ups, which read as genuine and specific (e.g., the GPS prompt write-up describes catching a real early scaling bug via an implausible EKF-origin coordinate). Recommend an independent check if this score needs firming up.

## Retrospective — `Report.md` (facts only, not scored)

125 lines. All five required dimensions covered, unusually well-organized — a clear framing of "code fails on inputs and succeeds on logic; prompts fail on logic and succeed on inputs" that's a genuinely useful way to state the tradeoff, plus a specific, honest account of a real scaling bug caught in the coded GPS solution.

## Individual understanding — N/A, assessed in class

---

The retrospective's code-vs-prompt framing is genuinely sharp, and the compass analysis is clean and correct throughout. The concrete, fixable thing here is real and worth addressing directly: sort out which GPS script is the actual deliverable — `analyze.py` already does the job correctly and is properly formatted, so pointing `README.md` and `Report.md` at it (instead of `analyze_gps.py`) is likely a fast fix that resolves most of this section's deductions.*
