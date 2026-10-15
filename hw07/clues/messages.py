"""messages.py -- the stage schemas (design.md, Section 1).

Each stage's answer is a pydantic model passed to the API as the output
schema (structured output), so the model's reply either validates or is
rejected. Field order matters: the model writes fields in schema order, so
every schema puts the evidence first and the verdict last.

Two fields are fixed by the contract (contract.py) because the given tools
and the planner read them: Relevance.relevance and ClueDecision.action (plus
search_radius_m for a converge).
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

import _kit  # noqa: F401  (puts lab/lesson7 on the path)
from contract import ACTIONS, Candidate, ClueAssessment, LatLon, MissionContext, StageCall  # noqa: F401

RelevanceLevel = Literal["high", "medium", "low", "none"]
ActionType = Literal["ignore", "log_only", "inspect_closer", "converge_search"]
assert set(ActionType.__args__) == set(ACTIONS)

Category = Literal["clothing", "footwear", "headwear", "bag", "toy", "sports_equipment", "personal_item",
                   "litter_or_debris", "natural", "other", "unknown"]
WearerSize = Literal["child", "adult", "any", "not_applicable", "unknown"]
Confidence = Literal["high", "medium", "low"]
Priority = Literal["high", "medium", "low"]


class Description(BaseModel):
    """Stage 2 output: what the object is, from the pixels alone."""
    observations: str = Field(description="What is visible before naming it: shapes, colours, markings, texture.")
    object_type: str = Field(description="Best short name for the object, e.g. \"child's baseball cap\".")
    category: Category
    colors: List[str] = Field(description="Main colours, most prominent first.")
    distinctive_features: List[str] = Field(description="Logos, patches, bows, buttons, laces, patterns.")
    estimated_size_cm: Optional[float] = Field(description="Longest dimension in cm from pixels x ground scale; "
                                                           "null if it can't be measured.")
    wearer_size: WearerSize = Field(description="For clothing, footwear and bags: who it would fit.")
    confidence: Confidence = Field(description="How sure you are of object_type.")
    needs_closer_look: bool = Field(description="True if you can't tell what it is, or a detail that would "
                                                "change the identification is unreadable.")


class Relevance(BaseModel):
    """Stage 3 output: is this evidence of THIS missing person?"""
    # R6 fix: listed BEFORE candidate_item so every plausible item is considered
    # before one is chosen (the single-choice field anchored on the first blue item).
    possible_items: List[str] = Field(description="Every listed clothing item or belonging whose kind, colour or "
                                                  "size the object is consistent with, copied from the person's "
                                                  "description. Empty if none.")
    candidate_item: Optional[str] = Field(description="The best of possible_items (most matches, fewest "
                                                      "mismatches); null if possible_items is empty.")
    matches: List[str] = Field(description="Specific attributes that agree with that item.")
    mismatches: List[str] = Field(description="Specific attributes that contradict it.")
    rationale: str = Field(description="One or two sentences tying matches and mismatches to the verdict.")
    relevance: RelevanceLevel   # required by the contract


class ClueDecision(BaseModel):
    """Stage 4 output: one action from the fixed menu."""
    rationale: str = Field(description="Why this action, in one or two sentences.")
    action: ActionType                       # required by the contract
    search_radius_m: Optional[float] = Field(default=None, description="converge_search only: metres, 30-150. "
                                                                       "Null for every other action.")
    priority: Optional[Priority] = Field(default=None, description="converge_search only; null otherwise.")
