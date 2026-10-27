from __future__ import annotations

import sys
import types


def hetero_data_class():
    if "torch_geometric.data.hetero_data" not in sys.modules:
        for name in (
            "torch_geometric.datasets",
            "torch_geometric.llm",
            "torch_geometric.contrib",
            "torch_geometric.graphgym",
        ):
            sys.modules.setdefault(name, types.ModuleType(name))

    from torch_geometric.data import HeteroData

    return HeteroData
