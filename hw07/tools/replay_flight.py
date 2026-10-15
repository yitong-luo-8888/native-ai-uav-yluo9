#!/usr/bin/env python3
"""replay_flight.py -- re-run the pipeline on candidates saved by detector.py in flight.

detector.py saves every candidate's crop (<id>.png) and metadata
(candidates.jsonl) under hw07/clues/data/flight/. This replays chosen ones
through ClueAnalyzer exactly as detector.py does (closer_look=None), with
every stage call traced, and scores each against the scenario clue at the
same position. Lets a failure seen on in-flight imagery be reproduced and
fixed without flying again.

    python hw07/tools/replay_flight.py hw07/scenarios/lost-boy-north-gate [--ids 2b99c35c ...] [--model M]
"""
import argparse
import base64
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLUES_DIR = os.path.normpath(os.path.join(HERE, "..", "clues"))
sys.path.insert(0, CLUES_DIR)

import _kit  # noqa: E402,F401
from contract import Candidate  # noqa: E402
from llm import ClaudeBackend  # noqa: E402
from llm_tools import TracingBackend  # noqa: E402
from pipeline import ClueAnalyzer  # noqa: E402
from scenario import load_scenario  # noqa: E402


def nearest_clue(scenario, lat, lon):
    def d(c):
        return math.hypot((c.lat - lat) * 111_000, (c.lon - lon) * 83_000)
    clue = min(scenario.clues, key=d)
    return clue if d(clue) < 5 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario")
    parser.add_argument("--flight-dir", default=os.path.join(CLUES_DIR, "data", "flight"))
    parser.add_argument("--ids", nargs="*", help="candidate ids (default: all in candidates.jsonl)")
    parser.add_argument("--model")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--closer-look-render", action="store_true",
                        help="offline closer look: the scenario's 6x render of the matching clue (as evaluate.py)")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    with open(os.path.join(args.flight_dir, "candidates.jsonl")) as f:
        saved = [json.loads(line) for line in f if line.strip()]
    if args.ids:
        saved = [c for c in saved if c["candidate_id"] in args.ids]
    inner = ClaudeBackend(model=args.model) if args.model else ClaudeBackend()
    backend = inner if args.quiet else TracingBackend(inner)
    rows, cost = [], 0.0
    for meta in saved:
        with open(os.path.join(args.flight_dir, f"{meta['candidate_id']}.png"), "rb") as f:
            crop = base64.standard_b64encode(f.read()).decode("ascii")
        candidate = Candidate(**{**meta, "crop_png_b64": crop, "context_png_b64": None})
        clue = nearest_clue(scenario, candidate.lat, candidate.lon)
        print(f"\n{'=' * 100}\nFLIGHT CANDIDATE {candidate.candidate_id} -> clue {clue.id if clue else '?'}"
              f" ({os.path.basename(clue.image) if clue else 'no clue here'})")
        closer = scenario.closer_look_for(clue) if (args.closer_look_render and clue) else None
        a = ClueAnalyzer(backend, scenario.mission, closer_look=closer,
                         on_event=lambda m: print(f"  >> {m}")).analyze(candidate)
        cost += a.cost_usd
        rel_ok = act_ok = None
        if clue:
            rel_ok = (a.relevance["relevance"] in ("high", "medium")) == clue.truth.relevant
            act_ok = a.decision["action"] in clue.truth.acceptable_actions
        rows.append((candidate.candidate_id, clue, a, rel_ok, act_ok))
    print(f"\n{'cand':9} {'clue':5} {'object':40} {'relevance':9} {'action':16} rel/act ok")
    for cid, clue, a, rel_ok, act_ok in rows:
        print(f"{cid:9} {clue.id if clue else '?':5} {a.object_type[:39]:40} {a.relevance['relevance']:9} "
              f"{a.decision['action']:16} {rel_ok}/{act_ok}")
    print(f"Cost ${cost:.3f}")


if __name__ == "__main__":
    main()
