#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Connection rules for auto-assembled chains.

A hand-wired chain is correct by construction; an auto-assembler is not, so this enforces the
stream contract:

- **Fan-out** (one source → many sinks) is illegal raw (a single ``ready``), so a
  :class:`~litedsp.stream.split.LiteDSPSplit` is inserted automatically.
- **Raw fan-in** (many sources → one sink) is rejected by netlist validation (route through a
  ``combine``/``mixer`` block, which has distinct sink ports).
- **Combinational loops** are rejected: v1 targets feed-forward chains, so any cycle in the block
  graph is an error.
- **Latency balancing** on reconvergent paths is automatic (``auto_delay=True``): when the
  branches feeding a multi-input block have unequal cumulative latency, a schema-preserving
  elastic delay of the exact deficit is inserted on the shorter
  branch(es). Insertions are deterministic (a pure function of the netlist) and reported via
  ``flow_inserted``, so chains stay predictable and bit-identical to hand-wired equivalents
  with explicit delays. Payload, parameter, ``first``, and ``last`` fields are preserved for
  every endpoint layout; with ``auto_delay=False`` unequal joins are reported as warnings.
"""

from functools import reduce
from operator  import and_

from migen import *

from litex.gen import LiteXModule
from litex.soc.interconnect import stream

from litedsp.flow.netlist import split_ref, NetlistError

# Schema-preserving stream glue -------------------------------------------------------------------

def endpoint_signature(endpoint_or_description):
    """Structural description used to reject lossy implicit connections."""
    description = getattr(endpoint_or_description, "description", endpoint_or_description)
    return (tuple(description.payload_layout), tuple(description.param_layout))

class _FlowSplit(LiteXModule):
    """Atomic fan-out retaining an endpoint's complete payload/param/framing schema."""
    def __init__(self, description, n):
        if n < 1:
            raise ValueError("expected n >= 1")
        self.latency = 0
        self.sink = stream.Endpoint(description)
        self.sources = [stream.Endpoint(description) for _ in range(n)]

        all_ready = reduce(and_, [source.ready for source in self.sources])
        self.comb += self.sink.ready.eq(all_ready)
        for source in self.sources:
            self.comb += [
                *self.sink.connect(source, omit={"valid", "ready"}),
                source.valid.eq(self.sink.valid & all_ready),
            ]

class _FlowDelay(LiteXModule):
    """Globally stalled elastic delay retaining payload, params, and frame markers."""
    def __init__(self, description, depth):
        if depth < 0:
            raise ValueError("expected depth >= 0")
        self.depth = depth
        self.latency = depth
        self.sink = stream.Endpoint(description)
        self.source = stream.Endpoint(description)
        if depth == 0:
            self.comb += self.sink.connect(self.source)
            return

        advance = Signal()
        self.comb += [
            advance.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(advance),
        ]
        payload_width = len(self.sink.payload)
        param_width   = len(self.sink.param)
        payload_pipe  = [Signal(payload_width) for _ in range(depth)] if payload_width else []
        param_pipe    = [Signal(param_width) for _ in range(depth)] if param_width else []
        valid_pipe    = Signal(depth)
        first_pipe    = Signal(depth)
        last_pipe     = Signal(depth)
        valid_next = self.sink.valid if depth == 1 else Cat(self.sink.valid, valid_pipe[:-1])
        first_next = self.sink.first if depth == 1 else Cat(self.sink.first, first_pipe[:-1])
        last_next  = self.sink.last  if depth == 1 else Cat(self.sink.last,  last_pipe[:-1])
        updates = [
            valid_pipe.eq(valid_next),
            first_pipe.eq(first_next),
            last_pipe.eq(last_next),
        ]
        if payload_width:
            updates += [
                payload_pipe[0].eq(self.sink.payload.raw_bits()),
                *[payload_pipe[k].eq(payload_pipe[k - 1]) for k in range(1, depth)],
            ]
        if param_width:
            updates += [
                param_pipe[0].eq(self.sink.param.raw_bits()),
                *[param_pipe[k].eq(param_pipe[k - 1]) for k in range(1, depth)],
            ]
        self.sync += If(advance, *updates)
        self.comb += [
            self.source.valid.eq(valid_pipe[-1]),
            self.source.first.eq(first_pipe[-1]),
            self.source.last.eq(last_pipe[-1]),
        ]
        if payload_width:
            self.comb += self.source.payload.raw_bits().eq(payload_pipe[-1])
        if param_width:
            self.comb += self.source.param.raw_bits().eq(param_pipe[-1])

# Cycle detection ----------------------------------------------------------------------------------

def _block_edges(nl):
    """Directed edges block_id -> block_id implied by the connections (top-level I/O excluded)."""
    edges = {}
    for c in nl.connections:
        s, _ = split_ref(c.src)
        d, _ = split_ref(c.dst)
        if nl.block(s) is not None and nl.block(d) is not None:
            edges.setdefault(s, set()).add(d)
    return edges

def _check_acyclic(nl):
    edges = _block_edges(nl)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {b.id: WHITE for b in nl.blocks}
    stack = []
    def visit(u):
        color[u] = GREY
        stack.append(u)
        for v in edges.get(u, ()):
            if color[v] == GREY:
                cycle = stack[stack.index(v):] + [v]
                raise NetlistError(f"combinational/feedback loop not supported in v1: "
                                   f"{' -> '.join(cycle)}")
            if color[v] == WHITE:
                visit(v)
        stack.pop()
        color[u] = BLACK
    for b in nl.blocks:
        if color[b.id] == WHITE:
            visit(b.id)

# Latency analysis ---------------------------------------------------------------------------------

def _latency_analysis(nl, reg, parent=None):
    """Cumulative-latency walk: returns ``(joins, incoming)``.

    ``joins`` maps each multi-input block id to ``{sink_port: arriving_latency}``.
    """
    lat = {}   # block_id -> cumulative latency from any input (best effort, longest path).
    edges = _block_edges(nl)
    order = _topo(nl, edges)
    incoming = {}
    for c in nl.connections:
        s, _ = split_ref(c.src)
        d, dport = split_ref(c.dst)
        incoming.setdefault(d, []).append((s, dport))
    for bid in order:
        preds = incoming.get(bid, [])
        base = max((lat.get(s, 0) for s, _ in preds), default=0)
        blat = 0
        if nl.block(bid):
            inst = getattr(parent, "_inst", {}).get(bid) if parent is not None else None
            l    = getattr(inst, "latency", reg[nl.block(bid).type].latency)
            blat = 0 if l is None else l  # None = variable/unknown; a real 0 stays 0.
        lat[bid] = base + (blat if isinstance(blat, int) else 0)
    joins = {}
    for bid, preds in incoming.items():
        if len(preds) > 1:
            joins[bid] = {dport: lat.get(s, 0) for s, dport in preds}
    return joins, incoming

def latency_deficits(nl, reg, parent=None):
    """Per-sink-ref alignment deficits: ``{"bid.port": cycles}`` to equalize each join."""
    joins, _ = _latency_analysis(nl, reg, parent=parent)
    deficits = {}
    for bid, arr in joins.items():
        target = max(arr.values())
        for dport, l in arr.items():
            if l < target:
                deficits[f"{bid}.{dport}"] = target - l
    return deficits

def latency_warnings(parent, nl, reg):
    """Warn when branches feeding a multi-sink block have unequal cumulative latency."""
    warns = []
    joins, _ = _latency_analysis(nl, reg, parent=parent)
    for bid, arr in joins.items():
        if len(set(arr.values())) > 1:
            warns.append(f"block '{bid}': inputs have unequal latency {arr} "
                         f"(insert a 'delay' block to align)")
    return warns

def _topo(nl, edges):
    seen, order = set(), []
    def visit(u):
        if u in seen:
            return
        seen.add(u)
        for v in edges.get(u, ()):
            visit(v)
        order.append(u)
    for b in nl.blocks:
        visit(b.id)
    return order[::-1]

# Connection ---------------------------------------------------------------------------------------

def connect_all(parent, nl, reg, auto_delay=True):
    """Wire every connection on ``parent``, inserting Split for fan-out and Delay for latency
    alignment (``auto_delay``). Returns inserted glue ids."""
    _check_acyclic(nl)

    fanout = {}
    for c in nl.connections:
        fanout.setdefault(c.src, []).append(c.dst)

    inserted = []
    deficits = latency_deficits(nl, reg, parent=parent) if auto_delay else {}

    def connect(src_ref, src_ep, dst_ref, dst_ep):
        src_signature = endpoint_signature(src_ep)
        dst_signature = endpoint_signature(dst_ep)
        if src_signature != dst_signature:
            raise NetlistError(f"concrete layout mismatch on {src_ref} -> {dst_ref}: "
                               f"{src_signature} != {dst_signature}")
        parent.comb += src_ep.connect(dst_ep)

    def sink_ep(dst_ref):
        """Sink endpoint for ``dst_ref``, behind an alignment Delay when the join needs one."""
        d = deficits.get(dst_ref, 0)
        if d == 0:
            return parent.endpoint(dst_ref)
        name = "delay_" + _safe(dst_ref)
        destination = parent.endpoint(dst_ref)
        dl = _FlowDelay(destination.description, depth=d)
        setattr(parent, name, dl)
        inserted.append(name)
        connect(name + ".source", dl.source, dst_ref, destination)
        return dl.sink

    for src_ref, dsts in fanout.items():
        src_ep = parent.endpoint(src_ref)
        if len(dsts) == 1:
            connect(src_ref, src_ep, dsts[0], sink_ep(dsts[0]))
            continue
        # Fan-out: preserve the source's exact endpoint description, including stream params.
        name = "split_" + _safe(src_ref)
        sp   = _FlowSplit(src_ep.description, n=len(dsts))
        setattr(parent, name, sp)
        inserted.append(name)
        connect(src_ref, src_ep, name + ".sink", sp.sink)
        for k, d in enumerate(dsts):
            connect(f"{name}.sources[{k}]", sp.sources[k], d, sink_ep(d))

    # Report joins that remain unbalanced when automatic insertion is disabled.
    if not auto_delay:
        for w in latency_warnings(parent, nl, reg):
            parent.flow_warnings.append(w)
    return inserted

def _safe(ref):
    return ref.replace(".", "_").replace("[", "_").replace("]", "")
