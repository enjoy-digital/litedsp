#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pure graph <-> netlist conversion for the editor (no DearPyGui dependency, fully testable).

The editor keeps a plain model: a list of *nodes* (``{id, type, params}``, where the pseudo-types
``__input__`` / ``__output__`` are top-level AXI-Stream ports) and a list of *links*
(``(src_ref, dst_ref)`` with refs like ``"id.port"`` or a bare top-level io id). These map directly
to a :class:`~litedsp.flow.netlist.Netlist`.
"""

from litedsp.flow import netlist as nlmod

INPUT_TYPE  = "__input__"
OUTPUT_TYPE = "__output__"

def model_to_netlist(meta, nodes, links):
    """Build a validated :class:`Netlist` from the editor model. Raises NetlistError if invalid."""
    inputs, outputs, blocks = [], [], []
    for n in nodes:
        if n["type"] == INPUT_TYPE:
            inputs.append({"id": n["id"], "layout": n.get("params", {}).get("layout", "iq")})
        elif n["type"] == OUTPUT_TYPE:
            outputs.append({"id": n["id"], "layout": n.get("params", {}).get("layout", "iq")})
        else:
            blocks.append({"id": n["id"], "type": n["type"], "params": n.get("params", {})})
    d = {
        "name":       meta.get("name", "chain"),
        "data_width": meta.get("data_width", 16),
        "clock_ns":   meta.get("clock_ns", 10.0),
        "inputs":     inputs,
        "outputs":    outputs,
        "blocks":     blocks,
        "connections": [{"from": s, "to": t} for s, t in links],
    }
    nl = nlmod.from_dict(d)
    nlmod.validate(nl)
    return nl

def netlist_to_model(nl):
    """Inverse: a :class:`Netlist` -> (nodes, links) for rendering."""
    nodes = []
    for io in nl.inputs:
        nodes.append({"id": io.id, "type": INPUT_TYPE,  "params": {"layout": io.layout}})
    for io in nl.outputs:
        nodes.append({"id": io.id, "type": OUTPUT_TYPE, "params": {"layout": io.layout}})
    for b in nl.blocks:
        nodes.append({"id": b.id, "type": b.type, "params": dict(b.params)})
    links = [(c.src, c.dst) for c in nl.connections]
    return nodes, links
