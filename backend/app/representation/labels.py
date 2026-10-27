"""Supervision label semantics for examiner judgement (Layer 3).

AIInterpretationStore holds adjacent AI interaction data; it is not part of core Layer 3.
"""

from __future__ import annotations

from enum import Enum


class ExaminerLinkRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"


EXAMINER_RELATIONS = frozenset({ExaminerLinkRelation.SUPPORTS.value, ExaminerLinkRelation.PARTIALLY_SUPPORTS.value})


class SupervisionLabel(str, Enum):
    """Explicit examiner labels only; UNLABELLED is never materialised as edges."""

    POSITIVE = "POSITIVE"
    PARTIAL = "PARTIAL"
    RETRACTED = "RETRACTED"


def supervision_for_relation(relation: str, *, active: bool) -> SupervisionLabel | None:
    if not active:
        return SupervisionLabel.RETRACTED
    if relation == ExaminerLinkRelation.SUPPORTS.value:
        return SupervisionLabel.POSITIVE
    if relation == ExaminerLinkRelation.PARTIALLY_SUPPORTS.value:
        return SupervisionLabel.PARTIAL
    return None
