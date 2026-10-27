from __future__ import annotations

from pathlib import Path

import pytest

from app.representation.instance import load_instance
from app.viz.networkx_adapter import _label, to_networkx

pytest.importorskip("networkx")

ASSESSMENT_ID = "C-JUN25-8464C1H-02_3"


def test_label_wraps_long_text():
    long_text = " ".join(["word"] * 30)
    wrapped = _label(long_text)
    assert "\n" in wrapped
    assert all(len(line) <= 24 for line in wrapped.splitlines())


def test_networkx_adapter_layers():
    instance = load_instance(data_dir="data", assessment_id=ASSESSMENT_ID)
    graph = to_networkx(instance, include_structural=False)
    layers = {data.get("layer") for _, data in graph.nodes(data=True)}
    assert "assessment" in layers


def test_write_dot(tmp_path):
    pydot = pytest.importorskip("pydot")
    assert pydot is not None
    from app.viz.render import write_dot

    instance = load_instance(data_dir="data", assessment_id=ASSESSMENT_ID)
    graph = to_networkx(instance, include_structural=False)
    dot_path = tmp_path / "sample.dot"
    write_dot(graph, dot_path)
    content = dot_path.read_text(encoding="utf-8")
    assert "cluster_assessment" in content
    assert "cluster_legend" in content
    assert "digraph" in content
    assert "Node types" in content
    assert "Edge types" in content
    assert "__legend__" in content
    assert "Question text" in content
    assert "REQUIRES" in content
