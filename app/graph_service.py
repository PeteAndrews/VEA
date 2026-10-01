from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Literal

from app.graph import AssessmentGraph, load_graph

EdgeKindFilter = Literal["assessment", "structural", "all"]


class GraphService:
    def __init__(self, graph: AssessmentGraph) -> None:
        self.graph = graph

    @classmethod
    def from_data_dir(
        cls,
        data_dir: str | Path = "data",
        assessment_id: str = "C-JUN25-8464C1H-02_3",
    ) -> GraphService:
        return cls(load_graph(data_dir=data_dir, assessment_id=assessment_id))

    def _node_summary(self, node_id: str) -> dict:
        node = self.graph.nodes[node_id]
        return {
            "id": node_id,
            "node_type": node["node_type"],
            "segment_type": node["segment_type"],
            "structural_only": node["structural_only"],
            "text": node["text"],
            "document_id": node["document_id"],
            "document_type": node["document_type"],
            "order": node["order"],
            "parent_id": node.get("parent_id"),
            "level": node.get("level"),
            "marks": node.get("marks"),
            "mark_range": node.get("mark_range"),
            "start_char": node.get("start_char"),
            "end_char": node.get("end_char"),
        }

    def get_node(self, node_id: str) -> dict:
        if node_id not in self.graph.nodes:
            raise KeyError(node_id)
        return self._node_summary(node_id)

    def get_outgoing(
        self,
        node_id: str,
        relation: str | None = None,
        kind: EdgeKindFilter = "all",
    ) -> list[dict]:
        self._require_node(node_id)
        edges = self._filter_edges(self.graph.out_edges.get(node_id, []), relation, kind)
        return [self._edge_view(e, "outgoing") for e in edges]

    def get_incoming(
        self,
        node_id: str,
        relation: str | None = None,
        kind: EdgeKindFilter = "all",
    ) -> list[dict]:
        self._require_node(node_id)
        edges = self._filter_edges(self.graph.in_edges.get(node_id, []), relation, kind)
        return [self._edge_view(e, "incoming") for e in edges]

    def get_neighbors(
        self,
        node_id: str,
        relation: str | None = None,
        kind: EdgeKindFilter = "all",
    ) -> list[dict]:
        self._require_node(node_id)
        results = []
        for edge in self.get_incoming(node_id, relation, kind):
            neighbor_id = edge["source"]
            results.append(
                {
                    "direction": "incoming",
                    "relation": edge["relation"],
                    "kind": edge["kind"],
                    "neighbor": self._node_summary(neighbor_id),
                    "edge": edge,
                }
            )
        for edge in self.get_outgoing(node_id, relation, kind):
            neighbor_id = edge["target"]
            results.append(
                {
                    "direction": "outgoing",
                    "relation": edge["relation"],
                    "kind": edge["kind"],
                    "neighbor": self._node_summary(neighbor_id),
                    "edge": edge,
                }
            )
        return results

    def get_context(self, node_id: str, include_structural: bool = False) -> dict:
        self._require_node(node_id)
        node = self.get_node(node_id)

        parent = self._meaningful_parent(node_id) if not include_structural else self._direct_parent(node_id)
        children = self._direct_children(node_id)
        if not include_structural:
            children = [child for child in children if not child["structural_only"]]

        incoming: dict[str, list[dict]] = {}
        outgoing: dict[str, list[dict]] = {}
        for edge in self.graph.in_edges.get(node_id, []):
            if edge["kind"] != "assessment":
                continue
            incoming.setdefault(edge["relation"], []).append(self._edge_view(edge, "incoming"))
        for edge in self.graph.out_edges.get(node_id, []):
            if edge["kind"] != "assessment":
                continue
            outgoing.setdefault(edge["relation"], []).append(self._edge_view(edge, "outgoing"))

        return {
            "node": node,
            "parent": parent,
            "children": children,
            "incoming": incoming,
            "outgoing": outgoing,
        }

    def find_path(
        self,
        source_id: str,
        target_id: str,
        relation: str | None = None,
        kind: EdgeKindFilter = "all",
    ) -> list[dict] | None:
        self._require_node(source_id)
        self._require_node(target_id)
        if source_id == target_id:
            return []

        queue: deque[tuple[str, list[dict]]] = deque([(source_id, [])])
        visited = {source_id}

        while queue:
            current_id, path = queue.popleft()
            for edge in self.graph.out_edges.get(current_id, []):
                if not self._edge_matches(edge, relation, kind):
                    continue
                next_id = edge["target"]
                step = self._path_step(edge, "outgoing")
                next_path = path + [step]
                if next_id == target_id:
                    return next_path
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, next_path))

            for edge in self.graph.in_edges.get(current_id, []):
                if not self._edge_matches(edge, relation, kind):
                    continue
                next_id = edge["source"]
                step = self._path_step(edge, "incoming")
                next_path = path + [step]
                if next_id == target_id:
                    return next_path
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, next_path))

        return None

    def assessment_overview(self) -> dict:
        criteria: list[dict] = []
        commentary: list[dict] = []
        question: list[dict] = []

        for node_id, node in self.graph.nodes.items():
            if node.get("segment_type") == "response_segment":
                continue
            summary = self._node_summary(node_id)
            if node["node_type"] in {"level", "level_rule", "mark_point"}:
                criteria.append(summary)
            elif node["node_type"] == "commentary":
                commentary.append(summary)
            elif node["document_type"] == "question" and not node["structural_only"]:
                question.append(summary)

        criteria.sort(key=lambda item: item["order"])
        commentary.sort(key=lambda item: item["order"])
        question.sort(key=lambda item: item["order"])

        return {
            "assessment_id": self.graph.assessment_id,
            "question": question,
            "criteria": criteria,
            "commentary": commentary,
        }

    def summary(self) -> dict:
        node_counts: dict[str, int] = {}
        for node_type in self.graph.data.node_types:
            node_counts[node_type] = int(self.graph.data[node_type].num_nodes)

        edge_counts: dict[str, int] = {}
        for edge_type in self.graph.data.edge_types:
            src, relation, dst = edge_type
            key = f"{src}--{relation}-->{dst}"
            edge_counts[key] = int(self.graph.data[edge_type].edge_index.size(1))

        return {
            "assessment_id": self.graph.assessment_id,
            "node_count": len(self.graph.nodes),
            "edge_count": self.graph.edge_count,
            "node_counts": node_counts,
            "edge_counts": edge_counts,
            "jev_labels": list(self.graph.jev_labels),
        }

    def _direct_parent(self, node_id: str) -> dict | None:
        for edge in self.graph.out_edges.get(node_id, []):
            if edge["relation"] == "PART_OF":
                return self._node_summary(edge["target"])
        return None

    def _meaningful_parent(self, node_id: str) -> dict | None:
        current_id = node_id
        visited: set[str] = set()
        while True:
            parent_id = None
            for edge in self.graph.out_edges.get(current_id, []):
                if edge["relation"] == "PART_OF":
                    parent_id = edge["target"]
                    break
            if parent_id is None or parent_id in visited:
                return None
            visited.add(parent_id)
            parent = self.graph.nodes[parent_id]
            if not parent["structural_only"]:
                return self._node_summary(parent_id)
            current_id = parent_id

    def _direct_children(self, node_id: str) -> list[dict]:
        children = [
            self._node_summary(edge["source"])
            for edge in self.graph.in_edges.get(node_id, [])
            if edge["relation"] == "PART_OF"
        ]
        children.sort(key=lambda child: child["order"])
        return children

    def _filter_edges(
        self,
        edges: list[dict],
        relation: str | None,
        kind: EdgeKindFilter,
    ) -> list[dict]:
        return [edge for edge in edges if self._edge_matches(edge, relation, kind)]

    def _edge_matches(self, edge: dict, relation: str | None, kind: EdgeKindFilter) -> bool:
        if relation and edge["relation"] != relation:
            return False
        if kind != "all" and edge["kind"] != kind:
            return False
        return True

    def _require_node(self, node_id: str) -> None:
        if node_id not in self.graph.nodes:
            raise KeyError(node_id)

    def _edge_view(self, edge: dict, direction: str) -> dict:
        view = {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge["relation"],
            "kind": edge["kind"],
            "direction": direction,
        }
        if edge["kind"] == "assessment":
            view.update(
                {
                    "llm_confidence": edge.get("llm_confidence"),
                    "llm_rationale": edge.get("llm_rationale"),
                    "llm_provenance": edge.get("llm_provenance"),
                    "jev_relation": edge.get("jev_relation"),
                    "jev_probability": edge.get("jev_probability"),
                    "jev_confidence": edge.get("jev_confidence"),
                    "jev_probabilities": edge.get("jev_probabilities"),
                    "agreement": edge.get("agreement"),
                    "needs_review": edge.get("needs_review"),
                }
            )
        return view

    def _path_step(self, edge: dict, direction: str) -> dict:
        step = {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge["relation"],
            "kind": edge["kind"],
            "direction": direction,
        }
        if edge["kind"] == "assessment":
            step["llm_confidence"] = edge.get("llm_confidence")
            step["jev_relation"] = edge.get("jev_relation")
        return step
