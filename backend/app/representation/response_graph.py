"""Layer 2: read-only candidate response graph (no AssessmentGraph mutation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.assessment_paths import resolve_response_paths


@dataclass(frozen=True)
class ResponseSegmentNode:
    id: str
    order: int
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class ResponseEdge:
    source: str
    target: str
    relation: str
    kind: str = "structural"


@dataclass
class ResponseGraph:
    response_id: str
    assessment_id: str
    text: str
    root_id: str
    segments: list[ResponseSegmentNode] = field(default_factory=list)
    edges: list[ResponseEdge] = field(default_factory=list)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> ResponseGraph:
        response_id = record["response_id"]
        assessment_id = record["assessment_id"]
        root_id = response_id
        segments = [
            ResponseSegmentNode(
                id=segment["id"],
                order=int(segment["order"]),
                text=segment["text"],
                start_char=int(segment["start_char"]),
                end_char=int(segment["end_char"]),
            )
            for segment in record.get("segments", [])
        ]
        segments.sort(key=lambda item: item.order)
        edges: list[ResponseEdge] = []
        for segment in segments:
            edges.append(ResponseEdge(source=segment.id, target=root_id, relation="PART_OF"))
        for index in range(len(segments) - 1):
            edges.append(
                ResponseEdge(
                    source=segments[index].id,
                    target=segments[index + 1].id,
                    relation="NEXT",
                )
            )
        return cls(
            response_id=response_id,
            assessment_id=assessment_id,
            text=record.get("text") or "",
            root_id=root_id,
            segments=segments,
            edges=edges,
        )

    def embeddings_pt_path(self, data_dir: str | Path) -> Path:
        paths = resolve_response_paths(data_dir, self.assessment_id, self.response_id)
        return paths.pt
