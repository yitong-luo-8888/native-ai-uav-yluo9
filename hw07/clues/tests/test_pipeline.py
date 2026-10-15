"""The three R8 unit tests -- no API key, no simulator.

    cd hw07/clues && python -m unittest discover tests

FakeBackend (lab/lesson7/llm_tools.py) returns scripted answers instead of
calling Claude and records every request in .requests, so these tests check
what each stage SENDS and how the pipeline reacts to what comes back.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import _kit  # noqa: E402,F401
from llm_tools import FakeBackend  # noqa: E402
from scenario import load_scenario  # noqa: E402

from pipeline import ClueAnalyzer  # noqa: E402
from stages import DECIDE, DESCRIBE, RELEVANCE, describe  # noqa: E402

LILY = os.path.join(_kit.KIT, "scenarios", "lost-girl-pinafore")


def description(needs_closer_look=False, **fields):
    return {"observations": "A small brown furry object with a red bow.", "object_type": "teddy bear",
            "category": "toy", "colors": ["brown", "red"], "distinctive_features": ["red bow"],
            "estimated_size_cm": 30.0, "wearer_size": "not_applicable", "confidence": "high",
            "needs_closer_look": needs_closer_look, **fields}


def relevance(level="high"):
    return {"possible_items": ["brown teddy bear with a red ribbon bow"],
            "candidate_item": "brown teddy bear with a red ribbon bow", "matches": ["teddy bear", "red bow"],
            "mismatches": [], "rationale": "Kind, colour and bow match.", "relevance": level}


def decision(action, radius=None):
    return {"rationale": "Policy.", "action": action, "search_radius_m": radius,
            "priority": "high" if action == "converge_search" else None}


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(LILY)
        self.clue = self.scenario.clues[0]
        self.candidate = self.scenario.candidate(self.clue)

    def test_describe_sends_the_crop_and_none_of_the_missing_persons_details(self):
        fake = FakeBackend({DESCRIBE: [description()]})
        describe(fake, self.candidate)
        sent = fake.requests[0]
        images = [b for b in sent["content"] if b["type"] == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["source"]["data"], self.candidate.crop_png_b64)
        person, mission = self.scenario.mission.person, self.scenario.mission
        text = " ".join(b["text"] for b in sent["content"] if b["type"] == "text") + sent["system"]
        for detail in [person.name, person.summary, mission.last_seen, *person.clothing, *person.belongings,
                       *person.other]:
            self.assertNotIn(detail, text)

    def test_closer_look_happens_at_most_once(self):
        zooms = []

        def closer_look(candidate):
            zooms.append(candidate.candidate_id)
            return self.scenario.candidate(self.clue, zoom=6.0)

        # Describe asks for a closer look every time, and Decide asks for inspect_closer every time.
        fake = FakeBackend({DESCRIBE: [description(True)] * 5, RELEVANCE: [relevance("medium")] * 5,
                            DECIDE: [decision("inspect_closer")] * 5})
        assessment = ClueAnalyzer(fake, self.scenario.mission, closer_look=closer_look).analyze(self.candidate)
        self.assertEqual(len(zooms), 1)
        self.assertEqual(len(assessment.descriptions), 2)
        self.assertEqual([r["stage"] for r in fake.requests], ["describe", "describe", "relevance", "decide"])
        self.assertNotEqual(assessment.decision["action"], "inspect_closer")   # the code guard ends it

    def test_converge_search_centre_is_the_candidates_position(self):
        # The model never sees or writes a position: the centre can only come from the candidate.
        fake = FakeBackend({DESCRIBE: [description()], RELEVANCE: [relevance("high")],
                            DECIDE: [decision("converge_search", radius=60.0)]})
        assessment = ClueAnalyzer(fake, self.scenario.mission).analyze(self.candidate)
        self.assertEqual(assessment.decision["action"], "converge_search")
        self.assertEqual((assessment.search_center.lat, assessment.search_center.lon),
                         (self.candidate.lat, self.candidate.lon))
        lkp = self.scenario.mission.last_known_point
        self.assertNotEqual((assessment.search_center.lat, assessment.search_center.lon), (lkp.lat, lkp.lon))
        self.assertEqual(assessment.decision["search_radius_m"], 60.0)


if __name__ == "__main__":
    unittest.main()
