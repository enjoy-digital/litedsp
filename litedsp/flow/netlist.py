#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tool-agnostic JSON description of a processing chain (the flow-graph netlist).

A netlist lists blocks (id + type + params), top-level AXI-Stream inputs/outputs, and the
connections between ports. Port references are ``"<block_id>.<port>"`` (e.g. ``"mix0.sink_a"``,
``"split0.sources[0]"``); top-level I/O are referenced by their bare id (``"in0"``). The GUI is
just a (de)serializer of this format; codegen (``builder``/``generate``) consumes it headless.

Example::

    {
      "name": "ddc", "data_width": 16, "clock_ns": 10.0,
      "inputs":  [{"id": "in0",  "layout": "iq"}],
      "outputs": [{"id": "out0", "layout": "iq"}],
      "blocks": [
        {"id": "nco0", "type": "nco",   "params": {}},
        {"id": "mix0", "type": "mixer", "params": {}}
      ],
      "connections": [
        {"from": "in0",         "to": "mix0.sink_a"},
        {"from": "nco0.source", "to": "mix0.sink_b"},
        {"from": "mix0.source", "to": "out0"}
      ]
    }
"""

import re
import json

from dataclasses import dataclass, field, asdict

from litedsp.flow import registry

# Errors -------------------------------------------------------------------------------------------

class NetlistError(Exception):
    """Raised when a netlist is structurally or semantically invalid."""

# Data model ---------------------------------------------------------------------------------------

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")   # CSR-safe identifier (becomes a submodule/CSR prefix).

@dataclass
class BlockNode:
    id: str
    type: str
    params: dict = field(default_factory=dict)

@dataclass
class Connection:
    src: str          # "block_id.port" or top-level input id.
    dst: str          # "block_id.port" or top-level output id.

@dataclass
class IO:
    id: str
    layout: str = "iq"

@dataclass
class Netlist:
    name: str = "chain"
    data_width: int = 16
    clock_ns: float = 10.0
    inputs: list = field(default_factory=list)        # [IO]
    outputs: list = field(default_factory=list)       # [IO]
    blocks: list = field(default_factory=list)        # [BlockNode]
    connections: list = field(default_factory=list)   # [Connection]
    csr_base: int = 0
    editor: dict = field(default_factory=dict)        # Editor hints (node positions); codegen ignores.

    # Lookups ------------------------------------------------------------------------------------
    def block(self, bid):
        for b in self.blocks:
            if b.id == bid:
                return b
        return None

    def io_ids(self):
        return {io.id for io in self.inputs} | {io.id for io in self.outputs}

# (De)serialization --------------------------------------------------------------------------------

def from_dict(d):
    return Netlist(
        name=d.get("name", "chain"),
        data_width=d.get("data_width", 16),
        clock_ns=d.get("clock_ns", 10.0),
        inputs=[IO(**io) for io in d.get("inputs", [])],
        outputs=[IO(**io) for io in d.get("outputs", [])],
        blocks=[BlockNode(id=b["id"], type=b["type"], params=b.get("params", {}))
                for b in d.get("blocks", [])],
        connections=[Connection(src=c["from"], dst=c["to"]) for c in d.get("connections", [])],
        csr_base=d.get("csr", {}).get("base_address", 0) if isinstance(d.get("csr"), dict) else 0,
        editor=d.get("editor", {}),
    )

def to_dict(nl):
    d = {
        "name": nl.name, "data_width": nl.data_width, "clock_ns": nl.clock_ns,
        "inputs":  [asdict(io) for io in nl.inputs],
        "outputs": [asdict(io) for io in nl.outputs],
        "blocks":  [{"id": b.id, "type": b.type, "params": b.params} for b in nl.blocks],
        "connections": [{"from": c.src, "to": c.dst} for c in nl.connections],
        "csr": {"base_address": nl.csr_base},
    }
    if nl.editor:
        d["editor"] = nl.editor
    return d

def loads(text):
    return from_dict(json.loads(text))

def load(path):
    with open(path) as f:
        return from_dict(json.load(f))

def dumps(nl):
    return json.dumps(to_dict(nl), indent=2)

def save(nl, path):
    with open(path, "w") as f:
        f.write(dumps(nl))

# Port reference resolution ------------------------------------------------------------------------

def split_ref(ref):
    """``"blk.port"`` -> ``("blk", "port")``; ``"io"`` -> ``("io", None)``."""
    if "." in ref:
        bid, port = ref.split(".", 1)
        return bid, port
    return ref, None

# Validation ---------------------------------------------------------------------------------------

def validate(nl, reg=None):
    """Raise :class:`NetlistError` on the first structural/semantic problem; else return ``nl``."""
    reg = reg or registry.registry()
    errors = []

    # Block ids: unique, CSR-safe, known type, known params.
    seen = set()
    io_ids = nl.io_ids()
    for b in nl.blocks:
        if not _ID_RE.match(b.id):
            errors.append(f"block id '{b.id}' is not a valid identifier (^[a-z][a-z0-9_]*$)")
        if b.id in seen or b.id in io_ids:
            errors.append(f"duplicate id '{b.id}'")
        seen.add(b.id)
        if b.type not in reg:
            errors.append(f"block '{b.id}': unknown type '{b.type}'")
            continue
        spec = reg[b.type]
        known = {p.name for p in spec.params}
        for k in b.params:
            if k not in known:
                errors.append(f"block '{b.id}' ({b.type}): unknown param '{k}' "
                              f"(known: {', '.join(sorted(known)) or 'none'})")

    for io in nl.inputs + nl.outputs:
        if not _ID_RE.match(io.id):
            errors.append(f"io id '{io.id}' is not a valid identifier")
        if io.layout not in ("iq", "iq_symbol", "real", "raw"):
            errors.append(f"io '{io.id}' has unknown layout '{io.layout}' "
                          f"(expected iq, iq_symbol, real, or raw)")

    # Connections: resolve endpoints, check direction + layout, single driver per sink.
    driven = {}     # sink ref -> count.
    def layout_of(ref, want_dir):
        bid, port = split_ref(ref)
        if port is None:
            io = next((x for x in (nl.inputs + nl.outputs) if x.id == bid), None)
            if io is None:
                errors.append(f"connection references unknown id '{bid}'")
                return None
            # Top-level input drives the graph (acts as a source); output is a sink.
            is_input = any(x.id == bid for x in nl.inputs)
            actual_dir = "source" if is_input else "sink"
            if actual_dir != want_dir:
                errors.append(f"top-level '{bid}' used on the wrong side of a connection")
            return io.layout
        b = nl.block(bid)
        if b is None or b.type not in reg:
            errors.append(f"connection references unknown block '{bid}'")
            return None
        p = reg[b.type].port(port)
        if p is None:
            ports = ", ".join(pp.name for pp in reg[b.type].ports)
            errors.append(f"block '{bid}' ({b.type}) has no port '{port}' (ports: {ports})")
            return None
        if p.direction != want_dir:
            errors.append(f"'{ref}' is a {p.direction}, expected a {want_dir}")
        return p.layout

    for c in nl.connections:
        lsrc = layout_of(c.src, "source")
        ldst = layout_of(c.dst, "sink")
        if lsrc is not None and ldst is not None and lsrc != ldst:
            errors.append(f"layout mismatch on {c.src} ({lsrc}) -> {c.dst} ({ldst})")
        driven[c.dst] = driven.get(c.dst, 0) + 1

    for dst, count in driven.items():
        if count > 1:
            errors.append(f"sink '{dst}' has {count} drivers (raw fan-in is illegal; "
                          f"route through a combine/mixer block)")

    if errors:
        raise NetlistError("invalid netlist '{}':\n  - {}".format(nl.name, "\n  - ".join(errors)))
    return nl
