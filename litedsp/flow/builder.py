#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Assemble a netlist into a connected LiteX module.

:class:`FlowChain` instantiates each netlist block as a *named submodule* (submodule name = netlist
id) so that ``get_csrs()`` recursively name-prefixes every block's CSRs into one conflict-free
register map. Top-level inputs/outputs become plain ``stream.Endpoint``s (wrapped as AXI-Stream by
the IP core in Phase 2). Connections + fan-out/loop rules are handled by :mod:`litedsp.flow.glue`.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common      import iq_layout, real_layout
from litedsp.flow        import registry, glue
from litedsp.flow.netlist import validate, split_ref

# Helpers ------------------------------------------------------------------------------------------

def _layout(kind, data_width):
    return real_layout(data_width) if kind == "real" else iq_layout(data_width)

def _build_kwargs(spec, params, data_width, with_csr):
    """Merge registry defaults + netlist params; inject data_width and with_csr where accepted."""
    kw = dict(spec.kwargs)
    kw.update(params)
    if any(p.name == "data_width" for p in spec.params) and "data_width" not in params:
        kw["data_width"] = data_width
    if spec.has_csr:
        kw["with_csr"] = with_csr
    return kw

# Flow chain ---------------------------------------------------------------------------------------

class FlowChain(LiteXModule):
    """A processing chain built from a :class:`~litedsp.flow.netlist.Netlist`."""
    def __init__(self, nl, reg=None, with_csr=True):
        self.reg = reg = reg or registry.registry()
        validate(nl, reg)
        self.netlist       = nl
        self.flow_warnings = []

        # Top-level I/O endpoints (chain head/tail; wrapped as AXI-Stream by the IP core).
        # name=io.id so the flattened Verilog ports are <id>_valid/<id>_payload_i/... (not anonymous).
        self.inputs  = {io.id: stream.Endpoint(_layout(io.layout, nl.data_width), name=io.id)
                        for io in nl.inputs}
        self.outputs = {io.id: stream.Endpoint(_layout(io.layout, nl.data_width), name=io.id)
                        for io in nl.outputs}

        # Instantiate blocks as named submodules (name = id -> automatic CSR prefixing).
        self._inst = {}
        for b in nl.blocks:
            spec = reg[b.type]
            inst = spec.cls(**_build_kwargs(spec, b.params, nl.data_width, with_csr))
            setattr(self, b.id, inst)
            self._inst[b.id] = inst

        # Connect everything (auto-insert Split for fan-out, reject loops).
        self.flow_inserted = glue.connect_all(self, nl, reg)

        # Convenience aliases so a single-in/single-out chain drops into run_stream()/connect().
        if len(self.inputs) == 1:
            self.sink = next(iter(self.inputs.values()))
        if len(self.outputs) == 1:
            self.source = next(iter(self.outputs.values()))

    # Resolve a netlist port reference to the actual Endpoint object.
    def endpoint(self, ref):
        bid, port = split_ref(ref)
        if port is None:
            if bid in self.inputs:
                return self.inputs[bid]
            if bid in self.outputs:
                return self.outputs[bid]
            raise KeyError(f"unknown top-level io '{bid}'")
        inst = self._inst[bid]
        if "[" in port:
            base, idx = port[:-1].split("[")
            return getattr(inst, base)[int(idx)]
        return getattr(inst, port)

    # Flattened top-level IO signals, for Verilog generation (chain head/tail + clock).
    def io_signals(self):
        ios = set()
        for ep in list(self.inputs.values()) + list(self.outputs.values()):
            ios |= set(ep.flatten())
        return ios
