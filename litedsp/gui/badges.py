#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-node resource/latency badges and chain totals (pure / testable, no DearPyGui).

Resource numbers come from ``impl/budgets.json`` (characterized per device by ``impl/run.py``);
latency comes from the reflected :class:`~litedsp.flow.metadata.BlockSpec`. Blocks without a
budget entry degrade gracefully to em-dashes.
"""

import os
import json

from litedsp.flow import registry
from litedsp.flow.glue import _block_edges, _topo
from litedsp.flow.netlist import split_ref

# Budgets ------------------------------------------------------------------------------------------

# Registry keys whose implementation sweep is characterized under a different budget name.
_ALIASES = {
    "fir_real":     "fir",
    "halfband_dec": "halfband",
    "halfband_int": "halfband",
    "equalizer":    "lms_equalizer",
    "parallel_fft": "fft_parallel_x2",
}

_BUDGETS = None

def budgets():
    """``impl/budgets.json`` contents (cached; empty dict when the file is absent)."""
    global _BUDGETS
    if _BUDGETS is None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(root, "impl", "budgets.json")
        if os.path.exists(path):
            with open(path) as f:
                _BUDGETS = json.load(f)
        else:
            _BUDGETS = {}
    return _BUDGETS

def budget_for(key, device="ecp5"):
    """The device resource dict for a registry ``key`` (or None when not characterized)."""
    return budgets().get(_ALIASES.get(key, key), {}).get(device)

# Node badges --------------------------------------------------------------------------------------

def badge_text(key, device="ecp5", reg=None):
    """Short footer string for one node, e.g. ``"LUT 566 · DSP 0 · 71 MHz · lat 1"``.

    Resources/fmax show "—" when the block has no budget entry; latency shows "—" when
    variable/unknown (BlockSpec.latency is None).
    """
    reg = reg or registry.registry()
    b   = budget_for(key, device) or {}
    lat = reg[key].latency if key in reg else None

    def fmt(v, suffix=""):
        return "—" if v is None else f"{v:g}{suffix}"

    return " · ".join([
        f"LUT {fmt(b.get('lut'))}",
        f"DSP {fmt(b.get('dsp'))}",
        fmt(b.get("fmax_min"), " MHz"),
        f"lat {fmt(lat if isinstance(lat, int) else None)}",
    ])

# Chain totals -------------------------------------------------------------------------------------

def chain_totals(nl, reg=None, device="ecp5"):
    """Whole-chain estimates from a :class:`~litedsp.flow.netlist.Netlist`.

    Returns ``{"lut", "ff", "dsp", "bram", "fmax_min", "latency", "budgeted", "blocks"}``:
    resource sums over budgeted blocks, the minimum characterized fmax, the total latency along
    the longest block path (same cumulative walk as :mod:`litedsp.flow.glue`), and how many of
    the chain's blocks have a budget entry.
    """
    reg = reg or registry.registry()
    totals = {"lut": 0, "ff": 0, "dsp": 0, "bram": 0, "fmax_min": None,
              "latency": 0, "budgeted": 0, "blocks": len(nl.blocks)}
    for b in nl.blocks:
        res = budget_for(b.type, device)
        if res is None:
            continue
        totals["budgeted"] += 1
        for m in ("lut", "ff", "dsp", "bram"):
            totals[m] += res.get(m, 0)
        fmax = res.get("fmax_min")
        if fmax is not None:
            totals["fmax_min"] = fmax if totals["fmax_min"] is None else min(totals["fmax_min"], fmax)

    # Longest-path latency: the cumulative walk of glue._latency_analysis, kept here so callers
    # get the path total (glue only exposes per-join deficits).
    edges    = _block_edges(nl)
    incoming = {}
    for c in nl.connections:
        s, _ = split_ref(c.src)
        d, _ = split_ref(c.dst)
        incoming.setdefault(d, []).append(s)
    lat = {}
    for bid in _topo(nl, edges):
        base = max((lat.get(s, 0) for s in incoming.get(bid, [])), default=0)
        l    = reg[nl.block(bid).type].latency if nl.block(bid) else None
        lat[bid] = base + (l if isinstance(l, int) else 0)
    totals["latency"] = max(lat.values(), default=0)
    return totals

def totals_text(totals):
    """Status-bar string for :func:`chain_totals`."""
    fmax = totals["fmax_min"]
    return (f"chain: LUT {totals['lut']} · FF {totals['ff']} · DSP {totals['dsp']} · "
            f"BRAM {totals['bram']} · {'—' if fmax is None else f'{fmax:g} MHz'} · "
            f"lat {totals['latency']} "
            f"({totals['budgeted']}/{totals['blocks']} blocks budgeted)")
