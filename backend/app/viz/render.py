"""Graphviz rendering via pydot (offline only)."""

from __future__ import annotations

import html as html_module
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import networkx as nx

try:
    import pydot
except ImportError:  # pragma: no cover - optional extra
    pydot = None

LAYER_CLUSTER = {
    "assessment": "cluster_assessment",
    "response": "cluster_response",
    "judgement": "cluster_judgement",
}

LAYER_TITLES = {
    "assessment": "Layer 1 — Assessment (mark scheme & question)",
    "response": "Layer 2 — Candidate response (segments)",
    "judgement": "Layer 3 — Examiner judgement",
}

NODE_FILL = {
    "question": "#dbeafe",
    "mark_point": "#dcfce7",
    "level": "#fef3c7",
    "level_rule": "#fde68a",
    "commentary": "#f3e8ff",
    "extra_info": "#e5e7eb",
    "response": "#cffafe",
    "evidence_span": "#fecdd3",
    "decision": "#fbcfe8",
}

NODE_TYPE_LABELS = {
    "question": "Question text",
    "mark_point": "Mark point / indicative detail",
    "level": "Level descriptor",
    "level_rule": "Level rule",
    "commentary": "Commentary / guidance",
    "extra_info": "Extra mark-scheme information",
    "response": "Response (root or segment)",
    "evidence_span": "Examiner evidence span",
    "decision": "Tentative level / final mark",
}

EDGE_COLOR = {
    "PART_OF": "#9ca3af",
    "NEXT": "#6b7280",
    "REQUIRES": "#dc2626",
    "CLARIFIES": "#2563eb",
    "CONSTRAINS": "#7c3aed",
    "REJECTS": "#b91c1c",
    "ACCEPTS": "#059669",
    "APPLIES_TO": "#0d9488",
    "APPLIES": "#0d9488",
    "REFERS_TO": "#64748b",
    "EXEMPLIFIES": "#0891b2",
    "EXTENDS": "#0284c7",
    "SUPPORTS": "#be123c",
    "PARTIALLY_SUPPORTS": "#db2777",
    "OVERLAPS": "#f97316",
    "ASSIGNS_LEVEL": "#a21caf",
}

EDGE_GLOSS = {
    "PART_OF": "Structural: child segment belongs to parent",
    "NEXT": "Structural: reading order between segments",
    "REQUIRES": "Assessment: level rule requires this criterion",
    "CLARIFIES": "Assessment: guidance clarifies a criterion",
    "CONSTRAINS": "Assessment: constrains how a criterion applies",
    "REJECTS": "Assessment: rejects / rules out interpretation",
    "ACCEPTS": "Assessment: accepts equivalent wording",
    "APPLIES_TO": "Assessment: guidance applies to target",
    "REFERS_TO": "Assessment: cross-reference between segments",
    "EXEMPLIFIES": "Assessment: example of criterion",
    "EXTENDS": "Assessment: extends another segment",
    "SUPPORTS": "Judgement: examiner links span as supporting criterion",
    "PARTIALLY_SUPPORTS": "Judgement: partial support for criterion",
    "OVERLAPS": "Alignment: evidence span overlaps response segment (chars)",
    "ASSIGNS_LEVEL": "Judgement: examiner tentative level on descriptor",
}

LEGEND_NODE_ID = "__legend__"


def _html_escape(text: str) -> str:
    return html_module.escape(text, quote=True)


def _edge_line_style(relation: str) -> str:
    if relation in {"PART_OF", "NEXT"}:
        return "dashed"
    if relation == "OVERLAPS":
        return "dotted"
    return "solid"


def _present_node_types(graph: nx.MultiDiGraph) -> list[str]:
    types = {data.get("node_type") or "mark_point" for _, data in graph.nodes(data=True)}
    order = list(NODE_TYPE_LABELS.keys())
    return [item for item in order if item in types] + sorted(types - set(order))


def _present_relations(graph: nx.MultiDiGraph) -> list[str]:
    relations = {data.get("relation") or "edge" for _, _, data in graph.edges(data=True)}
    priority = list(EDGE_GLOSS.keys())
    return [item for item in priority if item in relations] + sorted(relations - set(priority))


def _build_legend_html(graph: nx.MultiDiGraph) -> str:
    node_types = _present_node_types(graph)
    relations = _present_relations(graph)

    node_rows = ""
    for node_type in node_types:
        label = NODE_TYPE_LABELS.get(node_type, node_type.replace("_", " "))
        fill = NODE_FILL.get(node_type, "#ffffff")
        node_rows += (
            f'<TR><TD BGCOLOR="{fill}" ALIGN="LEFT">'
            f'<FONT POINT-SIZE="9">{_html_escape(label)}</FONT></TD></TR>\n'
        )

    edge_rows = ""
    for relation in relations:
        color = EDGE_COLOR.get(relation, "#374151")
        gloss = EDGE_GLOSS.get(relation, "Relation in exported graph")
        line_style = _edge_line_style(relation)
        edge_rows += (
            f"<TR><TD ALIGN=\"LEFT\">"
            f'<FONT POINT-SIZE="9" COLOR="{color}"><B>{_html_escape(relation)}</B></FONT> '
            f'<FONT POINT-SIZE="8" COLOR="#6b7280">({line_style})</FONT><BR/>'
            f'<FONT POINT-SIZE="8" COLOR="#4b5563">{_html_escape(gloss)}</FONT>'
            f"</TD></TR>\n"
        )

    if not node_types and not relations:
        return "<(empty graph)>"

    return f"""<
<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">
  <TR><TD COLSPAN="2" ALIGN="LEFT"><B><FONT POINT-SIZE="11">Legend</FONT></B></TD></TR>
  <TR>
    <TD VALIGN="TOP">
      <TABLE BORDER="0" CELLSPACING="2" CELLPADDING="3">
        <TR><TD><B><FONT POINT-SIZE="10">Node types</FONT></B></TD></TR>
        {node_rows}
      </TABLE>
    </TD>
    <TD VALIGN="TOP">
      <TABLE BORDER="0" CELLSPACING="2" CELLPADDING="3">
        <TR><TD><B><FONT POINT-SIZE="10">Edge types</FONT></B></TD></TR>
        {edge_rows}
      </TABLE>
    </TD>
  </TR>
</TABLE>
>"""


def _legend_anchor(graph: nx.MultiDiGraph) -> str | None:
    for node, data in graph.nodes(data=True):
        if data.get("node_type") == "question":
            return node
    for node, data in graph.nodes(data=True):
        if data.get("layer") == "assessment":
            return node
    nodes = list(graph.nodes)
    return nodes[0] if nodes else None


def _legend_cluster(graph: nx.MultiDiGraph) -> pydot.Cluster:
    legend = pydot.Cluster(
        "cluster_legend",
        label="",
        color="gray",
        style="rounded",
        margin="10",
        rank="source",
    )
    legend.add_node(
        pydot.Node(
            LEGEND_NODE_ID,
            shape="plain",
            label=_build_legend_html(graph),
        )
    )
    return legend


def write_dot(graph: nx.MultiDiGraph, path: Path) -> None:
    if pydot is None:
        raise RuntimeError("pydot is not installed. Install with: pip install -r requirements-viz.txt")
    dot = pydot.Dot(graph_type="digraph", rankdir="LR", compound="true")

    nodes_by_layer: dict[str, list[tuple[str, dict]]] = {"assessment": [], "response": [], "judgement": []}
    for node, data in graph.nodes(data=True):
        layer = data.get("layer", "assessment")
        nodes_by_layer.setdefault(layer, []).append((node, data))

    clusters: dict[str, pydot.Cluster] = {}
    for layer, items in nodes_by_layer.items():
        if not items:
            continue
        cluster_id = LAYER_CLUSTER.get(layer, f"cluster_{layer}")
        cluster = pydot.Cluster(cluster_id, label=LAYER_TITLES.get(layer, layer), color="black")
        clusters[layer] = cluster
        dot.add_subgraph(cluster)

    dot.add_subgraph(_legend_cluster(graph))

    for node, data in graph.nodes(data=True):
        layer = data.get("layer", "assessment")
        node_type = data.get("node_type") or "mark_point"
        cluster = clusters.get(layer, dot)
        cluster.add_node(
            pydot.Node(
                node,
                label=data.get("label") or node,
                shape="box",
                style="filled,rounded",
                fillcolor=NODE_FILL.get(node_type, "#ffffff"),
                fontsize="9",
                width="1.35",
                margin="0.08,0.06",
            )
        )

    for source, target, _key, data in graph.edges(keys=True, data=True):
        relation = data.get("relation") or "edge"
        color = EDGE_COLOR.get(relation, "#374151")
        style = "dashed" if data.get("kind") == "structural" else "solid"
        if data.get("active") is False:
            style = "dotted"
        if relation == "OVERLAPS":
            style = "dotted"
        dot.add_edge(
            pydot.Edge(
                source,
                target,
                label=relation,
                color=color,
                style=style,
                fontcolor=color,
                fontsize="8",
            )
        )

    anchor = _legend_anchor(graph)
    if anchor is not None:
        dot.add_edge(
            pydot.Edge(
                LEGEND_NODE_ID,
                anchor,
                style="invis",
                weight="10",
                minlen="1",
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dot.to_string(), encoding="utf-8")


def render_formats(dot_path: Path, formats: Iterable[str]) -> list[Path]:
    outputs: list[Path] = []
    dot_bin = shutil.which("dot")
    if dot_bin is None:
        return outputs
    for fmt in formats:
        out_path = dot_path.with_suffix(f".{fmt}")
        subprocess.run([dot_bin, f"-T{fmt}", str(dot_path), "-o", str(out_path)], check=False)
        if out_path.is_file():
            outputs.append(out_path)
    return outputs
