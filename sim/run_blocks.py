#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generic Verilator co-simulation: streaming blocks vs their NumPy golden models.

One generic C++ testbench (``sim/stream_tb.cpp``) is compiled per block against a generated
port map (``tb_ports.h``, derived from the block's sink/source stream layouts), so any
single-sink/single-source block with a model in ``test/models.py`` co-simulates bit-exact
without a dedicated testbench. Dedicated runners remain for the special shapes
(``run_nco.py``: no sink; ``run_fir.py``: complex FIR).

    python3 sim/run_blocks.py                        # all table entries
    python3 sim/run_blocks.py fir cic_decimator      # a selection
"""

import os
import sys
import random

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from litedsp.verilog import to_verilog
from sim.verilator   import build, run, have_verilator
from test import models

# Port map generation --------------------------------------------------------------------------------

def _fields(ep):
    """(name, width) payload fields of a stream Endpoint."""
    out = []
    for name, shape in ep.description.payload_layout:
        out.append((name, shape[0] if isinstance(shape, tuple) else shape))
    return out

def _ports_header(dut, top, path):
    """Generate tb_ports.h: typed port accessors for the generic testbench."""
    ins  = _fields(dut.sink) if hasattr(dut, "sink") else []
    outs = _fields(dut.source)
    set_body = " ".join(f"if (k == {k}) dut->sink_payload_{n} = (uint32_t)v;"
                        for k, (n, w) in enumerate(ins)) or "(void)dut; (void)k; (void)v;"
    get_body = " ".join(f"if (k == {k}) return ((int32_t)((uint32_t)dut->source_payload_{n}"
                        f" << {32 - w})) >> {32 - w};" for k, (n, w) in enumerate(outs))
    with open(path, "w") as f:
        f.write(f'#include "V{top}.h"\n'
                f"typedef V{top} TB_DUT;\n"
                f"#define TB_N_IN  {len(ins)}\n"
                f"#define TB_N_OUT {len(outs)}\n"
                f"static inline void tb_set_in(TB_DUT* dut, int k, int32_t v) {{ {set_body} }}\n"
                f"static inline int32_t tb_get_out(TB_DUT* dut, int k) {{ {get_body} return 0; }}\n")

# Block table ----------------------------------------------------------------------------------------
#
# Each spec returns (dut, ios_extra, columns_in, n_out, model) where model(columns) returns the
# expected output columns (arrays at least n_out long, compared bit-exact).

def _rand_cols(n_cols, n, lo=-20000, hi=20000, seed=1):
    prng = random.Random(seed)
    return [[prng.randint(lo, hi) for _ in range(n)] for _ in range(n_cols)]

def spec_fir():
    from litedsp.filter.fir    import FIRFilter
    from litedsp.filter.design import firwin_lowpass
    n, n_taps = 200, 17
    coeffs = firwin_lowpass(n_taps, 0.2)
    dut = FIRFilter(n_taps=n_taps, data_width=16)
    for t, c in enumerate(coeffs):
        dut.coeffs[t].reset = int(c)
    cols = _rand_cols(1, n)
    return dut, set(), cols, n - 8, lambda c: [models.fir_model(np.array(c[0]), coeffs)]

def spec_cic_decimator():
    from litedsp.filter.cic import CICDecimator
    n, R, N = 512, 8, 3
    dut  = CICDecimator(data_width=16, R=R, N=N, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, set(), cols, n//R - 4, lambda c: [models.cic_decimator_model(np.array(c[0]), R, N),
                                                  models.cic_decimator_model(np.array(c[1]), R, N)]

def spec_cic_interpolator():
    from litedsp.filter.cic import CICInterpolator
    n, R, N = 64, 8, 3
    dut  = CICInterpolator(data_width=16, R=R, N=N, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, set(), cols, n*R - 2*R, lambda c: [models.cic_interpolator_model(np.array(c[0]), R, N),
                                                   models.cic_interpolator_model(np.array(c[1]), R, N)]

def spec_dc_blocker():
    from litedsp.filter.dc_blocker import DCBlocker
    n    = 300
    dut  = DCBlocker(data_width=16, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, set(), cols, n - 4, lambda c: [models.dc_blocker_model(np.array(c[0])),
                                               models.dc_blocker_model(np.array(c[1]))]

def spec_moving_average():
    from litedsp.filter.moving_average import MovingAverage
    n, length_log2 = 300, 4
    dut  = MovingAverage(data_width=16, length_log2=length_log2, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, set(), cols, n - 4, lambda c: [models.moving_average_model(np.array(c[0]), length_log2),
                                               models.moving_average_model(np.array(c[1]), length_log2)]

def spec_magnitude():
    from litedsp.analysis.magnitude import Magnitude
    n    = 300
    dut  = Magnitude(data_width=16, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, set(), cols, n - 4, lambda c: [models.magnitude_model(np.array(c[0]), np.array(c[1]))]

SPECS = {
    "fir":              spec_fir,
    "cic_decimator":    spec_cic_decimator,
    "cic_interpolator": spec_cic_interpolator,
    "dc_blocker":       spec_dc_blocker,
    "moving_average":   spec_moving_average,
    "magnitude":        spec_magnitude,
}

# Runner ---------------------------------------------------------------------------------------------

def run_block(name, build_dir="/tmp/litedsp_sim"):
    dut, ios_extra, cols, n_out, model = SPECS[name]()
    bd  = os.path.join(build_dir, name)
    os.makedirs(bd, exist_ok=True)
    ios = ios_extra | {dut.source.valid, dut.source.ready} | set(
        getattr(dut.source, f) for f, _ in _fields(dut.source))
    if hasattr(dut, "sink"):
        ios |= {dut.sink.valid, dut.sink.ready} | set(
            getattr(dut.sink, f) for f, _ in _fields(dut.sink))
    _ports_header(dut, name, os.path.join(bd, "tb_ports.h"))
    verilog = to_verilog(dut, ios, name, bd)
    binary  = build(verilog, os.path.join(ROOT, "sim", "stream_tb.cpp"), name, bd,
        cflags=f"-I{os.path.abspath(bd)}")

    fin = os.path.join(bd, "in.txt")
    with open(fin, "w") as f:
        for row in zip(*cols) if cols else ():
            f.write(" ".join(str(v) for v in row) + "\n")
    fout = os.path.join(bd, "out.txt")
    run(binary, [fin, n_out, fout])

    got = np.loadtxt(fout).astype(int).reshape(n_out, -1)
    ref = model(cols)
    ok  = all(np.array_equal(got[:, k], np.asarray(r)[:n_out]) for k, r in enumerate(ref))
    print(f"{name:18s} Verilator co-sim: {n_out} samples, {got.shape[1]} field(s): "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        for k, r in enumerate(ref):
            if not np.array_equal(got[:, k], np.asarray(r)[:n_out]):
                print(f"  field {k}: got[:4]={got[:4, k].tolist()} ref[:4]={np.asarray(r)[:4].tolist()}")
    return ok

def main(argv=None):
    if not have_verilator():
        print("[skip] verilator not installed")
        return 0
    names = (argv or sys.argv[1:]) or list(SPECS)
    ok = all([run_block(n) for n in names])
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
