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
  branches feeding a multi-input block have unequal cumulative latency, a
  :class:`~litedsp.stream.delay.LiteDSPDelay` of the exact deficit is inserted on the shorter
  branch(es). Insertions are deterministic (a pure function of the netlist) and reported via
  ``flow_inserted``, so chains stay predictable and bit-identical to hand-wired equivalents
  with explicit delays. Joins the assembler cannot fix (non-I/Q sink ports) — or all joins,
  with ``auto_delay=False`` — are reported as warnings instead.
"""

from litedsp.stream.split import LiteDSPSplit
from litedsp.stream.delay import LiteDSPDelay
from litedsp.flow.netlist import split_ref, NetlistError

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

def _latency_analysis(nl, reg):
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
            l    = reg[nl.block(bid).type].latency
            blat = 0 if l is None else l  # None = variable/unknown; a real 0 stays 0.
        lat[bid] = base + (blat if isinstance(blat, int) else 0)
    joins = {}
    for bid, preds in incoming.items():
        if len(preds) > 1:
            joins[bid] = {dport: lat.get(s, 0) for s, dport in preds}
    return joins, incoming

def latency_deficits(nl, reg):
    """Per-sink-ref alignment deficits: ``{"bid.port": cycles}`` to equalize each join."""
    joins, _ = _latency_analysis(nl, reg)
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
    joins, _ = _latency_analysis(nl, reg)
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
    deficits = latency_deficits(nl, reg) if auto_delay else {}

    def sink_ep(dst_ref):
        """Sink endpoint for ``dst_ref``, behind an alignment Delay when the join needs one."""
        d = deficits.get(dst_ref, 0)
        if d == 0 or _layout_of(parent, dst_ref, reg, nl) != "iq":
            return parent.endpoint(dst_ref)                # Non-I/Q joins fall back to warnings.
        name = "delay_" + _safe(dst_ref)
        dl   = LiteDSPDelay(depth=d, data_width=nl.data_width)
        setattr(parent, name, dl)
        inserted.append(name)
        parent.comb += dl.source.connect(parent.endpoint(dst_ref))
        return dl.sink

    for src_ref, dsts in fanout.items():
        src_ep = parent.endpoint(src_ref)
        if len(dsts) == 1:
            parent.comb += src_ep.connect(sink_ep(dsts[0]))
            continue
        # Fan-out: insert a Split (I/Q only in v1).
        if _layout_of(parent, src_ref, reg, nl) != "iq":
            raise NotImplementedError(f"fan-out of a non-I/Q stream ('{src_ref}') is unsupported in v1")
        name = "split_" + _safe(src_ref)
        sp   = LiteDSPSplit(n=len(dsts), data_width=nl.data_width)
        setattr(parent, name, sp)
        inserted.append(name)
        parent.comb += src_ep.connect(sp.sink)
        for k, d in enumerate(dsts):
            parent.comb += sp.sources[k].connect(sink_ep(d))

    # Report joins that remain unbalanced (auto_delay off, or non-I/Q sink ports).
    if not auto_delay:
        for w in latency_warnings(parent, nl, reg):
            parent.flow_warnings.append(w)
    else:
        for ref, d in sorted(deficits.items()):
            if "delay_" + _safe(ref) not in inserted:
                parent.flow_warnings.append(f"input '{ref}' lags by {d} cycle(s) and is not I/Q "
                                            f"(insert an explicit delay to align)")
    return inserted

def _safe(ref):
    return ref.replace(".", "_").replace("[", "_").replace("]", "")

def _layout_of(parent, ref, reg, nl):
    bid, port = split_ref(ref)
    if port is None:
        io = next((x for x in (nl.inputs + nl.outputs) if x.id == bid), None)
        return io.layout if io else "iq"
    p = reg[nl.block(bid).type].port(port)
    return p.layout if p else "iq"
