"""Composable filters for graph visualisation subgraphs."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import networkx as nx


@dataclass
class VizFilter:
    node_types: frozenset[str] | None = None
    relations: frozenset[str] | None = None
    include_structural: bool = True
    seed_node_ids: frozenset[str] | None = None
    hops: int | None = None

    def apply(self, graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        working = graph.copy()
        if not self.include_structural:
            to_remove = [
                (u, v, key)
                for u, v, key, data in working.edges(keys=True, data=True)
                if data.get("kind") == "structural" or data.get("relation") in {"PART_OF", "NEXT"}
            ]
            working.remove_edges_from(to_remove)

        if self.relations is not None:
            to_remove = [
                (u, v, key)
                for u, v, key, data in working.edges(keys=True, data=True)
                if data.get("relation") not in self.relations
            ]
            working.remove_edges_from(to_remove)

        if self.node_types is not None:
            drop = [node for node, data in working.nodes(data=True) if data.get("node_type") not in self.node_types]
            working.remove_nodes_from(drop)

        if self.seed_node_ids and self.hops is not None:
            keep = _ego_nodes(working, self.seed_node_ids, self.hops)
            drop = [node for node in working.nodes if node not in keep]
            working.remove_nodes_from(drop)

        isolated = [node for node in working.nodes if working.degree(node) == 0]
        working.remove_nodes_from(isolated)
        return working


def _ego_nodes(graph: nx.MultiDiGraph, seeds: frozenset[str], hops: int) -> set[str]:
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    for seed in seeds:
        if seed in graph:
            queue.append((seed, 0))
            seen.add(seed)
    while queue:
        node, depth = queue.popleft()
        if depth >= hops:
            continue
        neighbours = set(graph.successors(node)) | set(graph.predecessors(node))
        for neighbour in neighbours:
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, depth + 1))
    return seen
