#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.comm.ofdm import LiteDSPCPInsert, LiteDSPCPRemove

from test.common import stream_driver, stream_capture

class TestCP(unittest.TestCase):
    def test_insert(self):
        N, CP = 16, 4
        dut = LiteDSPCPInsert(fft_size=N, cp_len=CP, data_width=16, with_csr=False)
        samples = [{"i": k + 1, "q": -(k + 1)} for k in range(2*N)]   # Two symbols.
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, 2*(N + CP), ("i", "q", "first", "last"),
                ready_rate=0.7),
        ])
        for s in range(2):
            sym  = [k + 1 + s*N for k in range(N)]
            want = sym[-CP:] + sym                          # Prefix = tail, then the symbol.
            got  = [c["i"] for c in cap[s*(N + CP):(s + 1)*(N + CP)]]
            self.assertEqual(got, want)
        firsts = [k for k, c in enumerate(cap) if c["first"]]
        lasts  = [k for k, c in enumerate(cap) if c["last"]]
        self.assertEqual(firsts, [0, N + CP])
        self.assertEqual(lasts,  [N + CP - 1, 2*(N + CP) - 1])

    def test_remove_round_trip(self):
        N, CP = 16, 4
        class Loop(LiteXModule):
            def __init__(self):
                self.ins = LiteDSPCPInsert(fft_size=N, cp_len=CP, data_width=16, with_csr=False)
                self.rem = LiteDSPCPRemove(fft_size=N, cp_len=CP, data_width=16, with_csr=False)
                self.sink, self.source = self.ins.sink, self.rem.source
                self.comb += self.ins.source.connect(self.rem.sink)
        dut = Loop()
        samples = [{"i": 3*k + 1, "q": -k} for k in range(3*N)]       # Three symbols.
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, 3*N, ("i", "q", "first", "last"), ready_rate=0.7),
        ])
        self.assertEqual([c["i"] for c in cap], [s["i"] for s in samples])
        self.assertEqual([k for k, c in enumerate(cap) if c["first"]], [0, N, 2*N])

if __name__ == "__main__":
    unittest.main()
