#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Verilator-lint every flow-registry block (the full palette).

Verilog-level portability check under a second tool's semantics (width/latch/comb-loop
classes of issues), covering the whole flow registry — the co-simulation runners then check
bit-exactness for the blocks with NumPy models. IOs are derived by reflection: every stream
endpoint (via ``litedsp.flow.metadata._ports``) plus every plain control Signal attribute, so
controls stay live instead of constant-folding away.

    python3 sim/run_lint.py
"""

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from migen import Signal

from litedsp.flow.registry import registry
from litedsp.flow.metadata import _ports
from litedsp.flow.generate import emit_verilog
from sim.verilator import lint, have_verilator

# IO discovery -------------------------------------------------------------------------------------

def _endpoint(dut, name):
    """Resolve a :func:`litedsp.flow.metadata._ports` name (``sink``, ``sink_a``, ``sinks[0]``)."""
    if "[" in name:
        attr, idx = name[:-1].split("[")
        return getattr(dut, attr)[int(idx)]
    return getattr(dut, name)

def _ios(dut):
    """All stream-endpoint signals + plain control Signal attributes (and lists thereof).

    ``reset`` is excluded: the ``@ResetInserter`` reset is driven from ``sys_rst`` by the
    ``to_verilog`` top wrapper.
    """
    ios = set()
    for p in _ports(dut):
        ios |= set(_endpoint(dut, p.name).flatten())
    for attr in dir(dut):
        if attr.startswith("__") or attr == "reset":
            continue
        try:
            v = getattr(dut, attr)
        except Exception:
            continue
        if isinstance(v, Signal):
            ios.add(v)
        elif isinstance(v, (list, tuple)) and len(v) and all(isinstance(e, Signal) for e in v):
            ios |= set(v)
    return ios

def _build(spec):
    """Instantiate a registry block with its default kwargs (CSR-less where supported)."""
    kwargs = dict(spec.kwargs)
    if spec.has_csr:
        kwargs["with_csr"] = False
    return spec.cls(**kwargs)

# Known failures -----------------------------------------------------------------------------------
#
# Real codegen issue *found by this sweep*, kept visible as XFAIL rather than papered over:
# LiteDSPDelay(depth=1) (the registry default) shifts ``v_pipe.eq(Cat(sink.valid, v_pipe[:-1]))``
# with a 1-bit ``v_pipe``; Migen prints the empty slice as ``v_pipe[-1:0]``, which is illegal
# Verilog (hard Verilator error). depth >= 2 lints clean; the fix belongs in
# litedsp/stream/delay.py (special-case the depth == 1 valid pipeline).
KNOWN_FAIL = {}

# Runner -------------------------------------------------------------------------------------------

def main(build_root="/tmp/litedsp_lint"):
    if not have_verilator():
        print("[skip] verilator not installed")
        return 0
    unexpected, skips, n_clean = [], [], 0
    for name, spec in sorted(registry().items()):
        # "_dut" suffix: a top named like one of its ports (e.g. gain) breaks Verilator's C model.
        top = name + "_dut"
        try:
            dut     = _build(spec)
            verilog = emit_verilog(dut, _ios(dut), top, os.path.join(build_root, name))
        except Exception as e:
            print(f"{name:20s} verilator lint: SKIP ({type(e).__name__}: {e})")
            traceback.print_exc(limit=1)
            skips.append(name)
            continue
        ok = lint(verilog, top)
        # Known codegen bug (see KNOWN_FAIL): expected to fail until the block is fixed; a
        # surprise pass means the table is stale and must be pruned.
        if name in KNOWN_FAIL:
            verdict = "XPASS (stale KNOWN_FAIL entry?)" if ok else f"XFAIL ({KNOWN_FAIL[name]})"
            print(f"{name:20s} verilator lint: {verdict}")
            if ok:
                unexpected.append(name)
            continue
        print(f"{name:20s} verilator lint: {'PASS' if ok else 'FAIL'}")
        if ok:
            n_clean += 1
        else:
            unexpected.append(name)
    n_xfail = sum(1 for n in KNOWN_FAIL if n not in unexpected and n not in skips)
    print(f"\n{n_clean}/{len(registry()) - n_xfail} blocks lint clean"
          + (f", {n_xfail} known codegen bug(s) (XFAIL, see KNOWN_FAIL)" if n_xfail else "")
          + (f", skipped: {', '.join(skips)}" if skips else ""))
    if unexpected:
        print(f"FAILED: {', '.join(unexpected)}")
    return 1 if (unexpected or skips) else 0

if __name__ == "__main__":
    sys.exit(main())
