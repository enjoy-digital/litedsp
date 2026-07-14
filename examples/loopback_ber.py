#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Self-checking loopback harness built from the new bring-up blocks.

A ``LiteDSPPatternSource`` (PRBS) is fanned out by ``LiteDSPSplit`` into a *reference* path (a ``LiteDSPDelay``) and a
*receive* path (a ``LiteDSPStreamFIFO``); an ``LiteDSPErrorCounter`` then compares the two streams sample by
sample. Because the error counter joins the two streams in order, differing per-path latency is
absorbed and a lossless chain yields zero errors — drop any lossy/erroring block into the RX path
and the error count rises. This is the template for an on-FPGA BER/integrity self-test driven
entirely from the bus (PatternSource + ErrorCounter both expose CSRs in a real design).

Run ``python3 examples/loopback_ber.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.generation.pattern import LiteDSPPatternSource, PATTERN_PRBS
from litedsp.stream.split       import LiteDSPSplit
from litedsp.stream.delay       import LiteDSPDelay
from litedsp.stream.fifo        import LiteDSPStreamFIFO
from litedsp.analysis.measure   import LiteDSPErrorCounter

# Loopback -----------------------------------------------------------------------------------------

class Loopback(LiteXModule):
    def __init__(self, data_width=16, fifo_depth=16, ref_delay=4):
        self.src   = LiteDSPPatternSource(data_width=data_width, seed=0xACE1, with_csr=False)
        self.split = LiteDSPSplit(n=2, data_width=data_width)
        self.delay = LiteDSPDelay(depth=ref_delay, data_width=data_width)        # Reference path.
        self.fifo  = LiteDSPStreamFIFO(depth=fifo_depth, data_width=data_width, with_csr=False)  # RX path.
        self.ec    = LiteDSPErrorCounter(data_width=data_width, with_csr=False)
        self.comb += [
            self.src.mode.eq(PATTERN_PRBS),
            self.src.source.connect(self.split.sink),
            self.split.sources[0].connect(self.delay.sink),
            self.split.sources[1].connect(self.fifo.sink),
            self.delay.source.connect(self.ec.sink_ref),
            self.fifo.source.connect(self.ec.sink_rx),
        ]

# Demo ---------------------------------------------------------------------------------------------

def main():
    n   = 1000
    dut = Loopback()
    res = {}
    def checker():
        for _ in range(8*n):
            if (yield dut.ec.total) >= n:
                break
            yield
        res["errors"] = (yield dut.ec.errors)
        res["total"]  = (yield dut.ec.total)
    run_simulation(dut, [checker()])

    print(f"Loopback BER harness: compared {res['total']} samples, {res['errors']} errors")
    assert res["total"] >= n, res
    assert res["errors"] == 0, res
    print("  PASS: PRBS survived Split -> {Delay | FIFO} -> ErrorCounter with zero errors")

if __name__ == "__main__":
    main()
