"""stages.py -- Stages 2-4: each declared once, then one function each.

A StageSpec (contract.py) is the single place a stage is defined: its name
(which is also its prompt file, prompts/<name>.md), the schema its answer
must fit, and how hard the model thinks (effort). Everything else -- the
backend, the tracer, FakeBackend in the tests -- reads the spec.

Each function builds the request for its stage from typed inputs and calls

    backend.generate(SPEC, load_prompt(SPEC), content) -> (result, StageCall)

What each request contains is justified in design.md, Section 1: Describe
sees only the pixels and their scale (never the mission); Relevance and
Decide see text only (never the image, never coordinates).
"""
import json
import os

import _kit  # noqa: F401
from contract import StageSpec
from geolocate import distance_m
from llm_tools import image_block
from messages import ClueDecision, Description, Relevance

DESCRIBE = StageSpec("describe", Description, effort="medium")    # the foundation: reads a ~20 px object
RELEVANCE = StageSpec("relevance", Relevance, effort="medium")    # the judgement the near misses test
DECIDE = StageSpec("decide", ClueDecision, effort="low")          # a policy lookup; no room to argue past it
STAGES = (DESCRIBE, RELEVANCE, DECIDE)

PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def load_prompt(spec):
    with open(os.path.join(PROMPT_DIR, f"{spec.name}.md"), encoding="utf-8") as f:
        return f.read()


def _text(text):
    return {"type": "text", "text": text}


def _person_text(mission):
    p = mission.person
    lines = [f"MISSING PERSON: {p.name}" + (f", age {p.age}" if p.age is not None else ""),
             f"Summary: {p.summary}"]
    for title, items in (("Clothing", p.clothing), ("Belongings", p.belongings), ("Other details", p.other)):
        if items:
            lines.append(f"{title}:")
            lines.extend(f"  - {item}" for item in items)
    lines.append(f"Last seen: {mission.last_seen}")
    if mission.conditions:
        lines.append(f"Conditions: {mission.conditions}")
    return "\n".join(lines)


def describe(backend, candidate):
    """Stage 2: what is this object? Sees only the crop and its scale, never the mission."""
    view = "ZOOMED closer-look view (6x)" if candidate.zoomed else "normal search-altitude view"
    facts = [f"Top-down drone camera crop, {view}."]
    if candidate.ground_m_per_px:
        facts.append(f"Ground scale: {candidate.ground_m_per_px * 100:.2f} cm per pixel of this crop "
                     f"(life-size), so measure the object in pixels and multiply.")
    else:
        facts.append("Ground scale: unknown.")
    facts.append("Describe the object at the centre of the crop.")
    content = [image_block(candidate.crop_png_b64), _text("\n".join(facts))]
    return backend.generate(DESCRIBE, load_prompt(DESCRIBE), content)


def assess_relevance(backend, mission, candidate, description):
    """Stage 3: is this object evidence of THIS missing person? Text only: the
    person and Describe's answer, not the image or the coordinates."""
    content = [_text(_person_text(mission)),
               _text("OBJECT FOUND BY THE DRONE (Stage 2 description, from the image alone):\n"
                     + json.dumps(description.model_dump(), indent=2))]
    return backend.generate(RELEVANCE, load_prompt(RELEVANCE), content)


def decide_action(backend, mission, candidate, description, relevance, already_inspected):
    """Stage 4: one action from the fixed menu (contract.ACTIONS).
    already_inspected: a closer look has been taken; don't offer inspect_closer again."""
    lkp = mission.last_known_point
    dist = distance_m(lkp.lat, lkp.lon, candidate.lat, candidate.lon)
    facts = [f"Searching for {mission.person.name}; last seen {mission.last_seen}.",
             f"Object: {description.object_type} (describe confidence {description.confidence}).",
             f"Distance from the last known point: {dist:.0f} m (computed by the planner).",
             "A closer look HAS ALREADY BEEN TAKEN: inspect_closer is not available."
             if already_inspected else "No closer look has been taken yet: inspect_closer is available.",
             "RELEVANCE ASSESSMENT (Stage 3):\n" + json.dumps(relevance.model_dump(), indent=2)]
    return backend.generate(DECIDE, load_prompt(DECIDE), [_text("\n".join(facts))])
