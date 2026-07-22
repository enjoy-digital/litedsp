#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Assemble a netlist into a connected LiteX module.

:class:`LiteDSPFlowChain` instantiates each netlist block as a *named submodule* (submodule name = netlist
id) so that ``get_csrs()`` recursively name-prefixes every block's CSRs into one conflict-free
register map. Top-level inputs/outputs become plain ``stream.Endpoint``s (wrapped as AXI-Stream by
the IP core in Phase 2). Connections + fan-out/loop rules are handled by :mod:`litedsp.flow.glue`.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common      import iq_layout, iq_symbol_layout, real_layout
from litedsp.flow        import registry, glue
from litedsp.flow.netlist import validate, split_ref, NetlistError

# Helpers ------------------------------------------------------------------------------------------

def _layout(kind, data_width):
    if kind == "real":
        return real_layout(data_width)
    if kind == "iq_symbol":
        return iq_symbol_layout(data_width)
    return iq_layout(data_width)

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

class LiteDSPFlowChain(LiteXModule):
    """A processing chain built from a :class:`~litedsp.flow.netlist.Netlist`.

    ``auto_delay=True`` (default) inserts schema-preserving elastic delays on reconvergent paths
    with unequal branch latency (reported in ``flow_inserted``); with ``auto_delay=False``
    unbalanced joins are only warned about (``flow_warnings``).
    """
    def __init__(self, nl, reg=None, with_csr=True, auto_delay=True):
        self.reg = reg = reg or registry.registry()
        validate(nl, reg)
        self.netlist       = nl
        self.flow_warnings = []

        # Instantiate blocks as named submodules (name = id -> automatic CSR prefixing).
        self._inst = {}
        for b in nl.blocks:
            spec = reg[b.type]
            inst = spec.cls(**_build_kwargs(spec, b.params, nl.data_width, with_csr))
            setattr(self, b.id, inst)
            self._inst[b.id] = inst

        # Top-level I/O endpoints (chain head/tail; wrapped as AXI-Stream by the IP core).
        # Infer the complete EndpointDescription from connected block ports. The JSON ``layout``
        # is a palette/validation category, not a sufficient wire schema for FEC widths, FFT
        # exponent params, timestamps, or other raw streams. Unconnected/direct I/O retains the
        # backward-compatible built-in layout fallback.
        self.inputs  = {io.id: stream.Endpoint(self._io_description(io, is_input=True), name=io.id)
                        for io in nl.inputs}
        self.outputs = {io.id: stream.Endpoint(self._io_description(io, is_input=False), name=io.id)
                        for io in nl.outputs}

        # Connect everything (auto-insert Split/Delay glue, reject loops).
        self.flow_inserted = glue.connect_all(self, nl, reg, auto_delay=auto_delay)

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

    def _io_description(self, io, is_input):
        refs = ([c.dst for c in self.netlist.connections if c.src == io.id] if is_input else
                [c.src for c in self.netlist.connections if c.dst == io.id])
        descriptions = []
        for ref in refs:
            bid, port = split_ref(ref)
            if port is None:                                   # Direct top-level I/O connection.
                continue
            inst = self._inst.get(bid)
            if inst is not None:
                descriptions.append(self._instance_endpoint(inst, port).description)
        if not descriptions:
            if io.layout == "raw":
                raise NetlistError(f"top-level raw I/O '{io.id}' must connect to a block port "
                                   f"so its concrete endpoint schema can be inferred")
            return stream.EndpointDescription(_layout(io.layout, self.netlist.data_width))
        signature = glue.endpoint_signature(descriptions[0])
        for description in descriptions[1:]:
            if glue.endpoint_signature(description) != signature:
                side = "destinations" if is_input else "drivers"
                raise NetlistError(
                    f"top-level '{io.id}' has incompatible concrete {side}: {signature} vs "
                    f"{glue.endpoint_signature(description)}")
        return descriptions[0]

    @staticmethod
    def _instance_endpoint(inst, port):
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
