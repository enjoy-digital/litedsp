#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generic Verilator co-simulation: streaming blocks vs their NumPy golden models.

One generic C++ testbench (``sim/stream_tb.cpp``) is compiled per block against a generated
port map (``tb_ports.h``, derived from the block's sink/source stream layouts), so any block
with 0..N sinks, one source and a model in ``test/models.py`` co-simulates bit-exact under
seeded-random backpressure without a dedicated testbench. The block table lives in
``sim/cosim_specs.py`` (one entry per cosim-eligible block of ``test/registry.py``).
Dedicated runners remain as focused examples (``run_nco.py``, ``run_fir.py``).

    python3 sim/run_blocks.py                        # all table entries
    python3 sim/run_blocks.py fir_real cic_decimator # a selection
    python3 sim/run_blocks.py --seed 3               # another backpressure timing pattern
    python3 sim/run_blocks.py --list                 # list table entries
"""

import os
import sys
import argparse

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from litedsp.flow.metadata import _ports
from litedsp.flow.generate import emit_verilog
from sim.verilator         import build, run, have_verilator
from sim.cosim_specs       import SPECS, KNOWN_FAIL, check_coverage

# Port discovery -----------------------------------------------------------------------------------

def _endpoint(dut, name):
    """Resolve a :func:`litedsp.flow.metadata._ports` name (``sink``, ``sink_a``, ``sinks[0]``)."""
    if "[" in name:
        attr, idx = name[:-1].split("[")
        return getattr(dut, attr)[int(idx)]
    return getattr(dut, name)

def _fields(ep):
    """(name, width, signed) payload fields of a stream Endpoint."""
    out = []
    for name, shape in ep.description.payload_layout:
        if isinstance(shape, tuple):
            out.append((name, shape[0], bool(shape[1])))
        else:
            out.append((name, shape, False))
    return out

def _stream_ports(dut):
    """(verilog_prefix, endpoint) for all sinks (discovery order) + the single source.

    Migen flattens a Record named ``<attr>`` to ports ``<attr>_valid`` / ``<attr>_payload_<f>``
    (verified for ``sink``, ``sink_a``); endpoints held in a *list* attribute are anonymous to
    Migen's tracer (ports would come out as ``valid``, ``valid_1``, ...), so ``sinks[k]`` gets
    pinned to the same convention (``sinks{k}_*``) via ``name_override`` here.
    """
    sinks, sources = [], []
    for p in _ports(dut):
        ep     = _endpoint(dut, p.name)
        prefix = p.name.replace("[", "").replace("]", "")
        if "[" in p.name:  # Anonymous list endpoint: pin deterministic port names.
            for attr in ("valid", "ready", "first", "last"):
                getattr(ep, attr).name_override = f"{prefix}_{attr}"
            for f, _, _ in _fields(ep):
                getattr(ep, f).name_override = f"{prefix}_payload_{f}"
        (sinks if p.direction == "sink" else sources).append((prefix, ep))
    assert len(sources) == 1, "generic TB expects exactly one source"
    return sinks, sources[0]

# Port map generation ------------------------------------------------------------------------------

def _ports_header(dut, top, path):
    """Generate tb_ports.h: typed per-sink/source port accessors for the generic testbench."""
    sinks, (src_prefix, src_ep) = _stream_ports(dut)
    outs = _fields(src_ep)

    set_valid, get_ready, set_in = [], [], []
    n_in = 0
    for s, (prefix, ep) in enumerate(sinks):
        set_valid.append(f"if (s == {s}) dut->{prefix}_valid = v;")
        get_ready.append(f"if (s == {s}) return dut->{prefix}_ready;")
        for f, w, _ in _fields(ep):
            set_in.append(f"if (k == {n_in}) dut->{prefix}_payload_{f} = (uint32_t)v;")
            n_in += 1
    get_out = []
    for k, (f, w, signed) in enumerate(outs):
        port = f"dut->{src_prefix}_payload_{f}"
        if signed or w >= 32:  # Sign-extend from the payload width (shift 0 when w == 32).
            get_out.append(f"if (k == {k}) return ((int32_t)((uint32_t){port} << {32 - w})) >> {32 - w};")
        else:                  # Unsigned payload (e.g. log2): plain zero-extended read.
            get_out.append(f"if (k == {k}) return (int32_t)(uint32_t){port};")

    void = "(void)dut; (void)s; (void)v;"
    with open(path, "w") as f:
        f.write(f'#include "V{top}.h"\n'
                f"typedef V{top} TB_DUT;\n"
                f"#define TB_N_SINKS {len(sinks)}\n"
                f"#define TB_N_IN    {n_in}\n"
                f"#define TB_N_OUT   {len(outs)}\n"
                f"static const int tb_sink_fields[{max(len(sinks), 1)}] = "
                f"{{{', '.join(str(len(_fields(ep))) for _, ep in sinks) or '0'}}};\n"
                f"static inline void tb_set_sink_valid(TB_DUT* dut, int s, int v) "
                f"{{ {' '.join(set_valid) or void} }}\n"
                f"static inline int tb_get_sink_ready(TB_DUT* dut, int s) "
                f"{{ {' '.join(get_ready) or '(void)dut; (void)s;'} return 0; }}\n"
                f"static inline void tb_set_in(TB_DUT* dut, int k, int32_t v) "
                f"{{ {' '.join(set_in) or '(void)dut; (void)k; (void)v;'} }}\n"
                f"static inline int32_t tb_get_out(TB_DUT* dut, int k) "
                f"{{ {' '.join(get_out)} return 0; }}\n")
    return sinks, (src_prefix, src_ep)

# Runner -------------------------------------------------------------------------------------------

def run_block(name, seed=1, throttle=25, ready_rate=75, build_dir="/tmp/litedsp_sim"):
    dut, cols, n_out, model = SPECS[name]()
    bd = os.path.join(build_dir, name)
    os.makedirs(bd, exist_ok=True)

    # "_dut" suffix: a top named like one of its signals (e.g. gain) breaks Verilator's C model.
    top = name + "_dut"
    sinks, (_, src_ep) = _ports_header(dut, top, os.path.join(bd, "tb_ports.h"))
    ios = {src_ep.valid, src_ep.ready} | {getattr(src_ep, f) for f, _, _ in _fields(src_ep)}
    for _, ep in sinks:
        ios |= {ep.valid, ep.ready} | {getattr(ep, f) for f, _, _ in _fields(ep)}
    assert len(cols) == sum(len(_fields(ep)) for _, ep in sinks), \
        f"{name}: {len(cols)} stimulus columns for {sum(len(_fields(ep)) for _, ep in sinks)} sink fields"

    verilog = emit_verilog(dut, ios, top, bd)          # Memory .init files land beside the .v.
    binary  = build(verilog, os.path.join(ROOT, "sim", "stream_tb.cpp"), top, bd,
        cflags=f"-I{os.path.abspath(bd)}")

    fin = os.path.join(bd, "in.txt")
    with open(fin, "w") as f:
        for row in zip(*cols) if cols else ():
            f.write(" ".join(str(v) for v in row) + "\n")
    fout = os.path.join(bd, "out.txt")
    run(binary, [fin, n_out, fout,
        "--seed", seed, "--throttle", throttle, "--ready-rate", ready_rate], cwd=bd)

    got = np.loadtxt(fout).astype(int).reshape(n_out, -1)
    ref = model(cols)
    ok  = all(np.array_equal(got[:, k], np.asarray(r)[:n_out]) for k, r in enumerate(ref))
    # Known RTL divergence (see cosim_specs.KNOWN_FAIL): expected to mismatch until the block
    # is fixed; a surprise match means the table is stale and must be pruned.
    if name in KNOWN_FAIL:
        verdict  = "XPASS (stale KNOWN_FAIL entry?)" if ok else f"XFAIL ({KNOWN_FAIL[name]})"
        expected = not ok
    else:
        verdict  = "PASS" if ok else "FAIL"
        expected = ok
    print(f"{name:18s} Verilator co-sim: {n_out:4d} samples, {len(sinks)} sink(s), "
          f"{got.shape[1]} field(s), seed={seed}: {verdict}")
    if not ok and name not in KNOWN_FAIL:
        for k, r in enumerate(ref):
            if not np.array_equal(got[:, k], np.asarray(r)[:n_out]):
                print(f"  field {k}: got[:4]={got[:4, k].tolist()} ref[:4]={np.asarray(r)[:4].tolist()}")
    return expected

def main(argv=None):
    parser = argparse.ArgumentParser(description="Verilator co-simulation of LiteDSP blocks vs NumPy models.")
    parser.add_argument("blocks", nargs="*",                 help="Blocks to run (default: all table entries).")
    parser.add_argument("--seed",       default=1,  type=int, help="Backpressure randomization seed.")
    parser.add_argument("--throttle",   default=25, type=int, help="Sink valid hold-back probability (%%).")
    parser.add_argument("--ready-rate", default=75, type=int, help="Source ready assert probability (%%).")
    parser.add_argument("--list",       action="store_true",  help="List table entries and exit.")
    parser.add_argument("--build-dir",  default="/tmp/litedsp_sim", help="Build directory.")
    args = parser.parse_args(argv)

    check_coverage()
    if args.list:
        for name in SPECS:
            print(name)
        return 0
    if not have_verilator():
        print("[skip] verilator not installed")
        return 0
    for name in args.blocks:
        if name not in SPECS:
            parser.error(f"unknown block '{name}' (see --list)")
    names   = args.blocks or list(SPECS)
    results = [run_block(n, seed=args.seed, throttle=args.throttle, ready_rate=args.ready_rate,
                         build_dir=args.build_dir) for n in names]
    n_xfail = sum(1 for n in names if n in KNOWN_FAIL)
    print(f"\n{sum(results) - n_xfail}/{len(names) - n_xfail} bit-exact"
          + (f", {n_xfail} known RTL bug(s) (XFAIL, see sim/cosim_specs.py)" if n_xfail else ""))
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
