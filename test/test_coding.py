#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.comm.mapper import LiteDSPSymbolMapper
from litedsp.comm.slicer import LiteDSPSlicer
from litedsp.comm.coding import LiteDSPScrambler, LiteDSPDescrambler, LiteDSPCRC, LiteDSPConvEncoder

from test.common import run_stream, column, to_signed, stream_driver, stream_capture

class TestMapper(unittest.TestCase):
    def test_map_then_slice(self):
        bpa, sp = 2, 6000           # 16-QAM.
        mapper = LiteDSPSymbolMapper(data_width=16, bits_per_axis=bpa, spacing=sp, with_csr=False)
        prng = random.Random(1)
        syms = [prng.randint(0, (1 << (2*bpa)) - 1) for _ in range(64)]
        cap = run_stream(mapper, [{"symbol": s} for s in syms], len(syms), ["symbol"],
            ["i", "q"], sink_throttle=0.1, source_ready_rate=0.8)
        pts = [{"i": int(i), "q": int(q)} for i, q in zip(to_signed(column(cap, "i"), 16),
                                                          to_signed(column(cap, "q"), 16))]
        slicer = LiteDSPSlicer(data_width=16, bits_per_axis=bpa, spacing=sp, with_csr=False)
        cap2 = run_stream(slicer, pts, len(pts), ["i", "q"], ["i", "q", "symbol"],
            sink_throttle=0.1, source_ready_rate=0.8)
        self.assertEqual(list(column(cap2, "symbol")), syms[:len(cap2)])

class TestScrambler(unittest.TestCase):
    def test_roundtrip(self):
        taps = (4, 7)
        prng = random.Random(2)
        bits = [prng.randint(0, 1) for _ in range(300)]
        scr = LiteDSPScrambler(taps=taps, with_csr=False)
        cs = run_stream(scr, [{"data": b} for b in bits], len(bits), ["data"], ["data"],
            sink_throttle=0.1, source_ready_rate=0.8)
        scrambled = list(column(cs, "data"))
        des = LiteDSPDescrambler(taps=taps, with_csr=False)
        cd = run_stream(des, [{"data": int(b)} for b in scrambled], len(scrambled), ["data"], ["data"],
            sink_throttle=0.1, source_ready_rate=0.8)
        rec = list(column(cd, "data"))
        # Self-synchronizing: matches after the register fills.
        self.assertEqual(rec[max(taps):], bits[max(taps):len(rec)])

class TestCRC(unittest.TestCase):
    def test_ccitt_check(self):
        msg = b"123456789"
        bits = [(byte >> (7 - i)) & 1 for byte in msg for i in range(8)]
        dut = LiteDSPCRC(width=16, poly=0x1021, init=0xFFFF, with_csr=False)
        crc_vals = []

        @passive
        def watch(dut):
            while True:
                crc_vals.append((yield dut.crc))
                yield
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in bits], ["data"], throttle=0.0),
            stream_capture(dut.source, [], len(bits), ["data"], ready_rate=1.0),
            watch(dut),
        ])
        self.assertEqual(crc_vals[-1], 0x29B1)   # CRC-16/CCITT-FALSE("123456789").

class TestConvEncoder(unittest.TestCase):
    def test_known_output(self):
        K, polys = 7, (0o171, 0o133)
        prng = random.Random(3)
        bits = [prng.randint(0, 1) for _ in range(100)]
        dut = LiteDSPConvEncoder(constraint=K, polys=polys, with_csr=False)
        cap = run_stream(dut, [{"data": b} for b in bits], len(bits), ["data"], ["data"],
            sink_throttle=0.1, source_ready_rate=0.8)
        got = list(column(cap, "data"))
        # Reference.
        reg, ref = 0, []
        for b in bits:
            full = b | (reg << 1)
            o = [bin(full & g).count("1") & 1 for g in polys]
            ref.append(o[0] | (o[1] << 1))
            reg = (b | (reg << 1)) & ((1 << (K - 1)) - 1)
        self.assertEqual(got, ref[:len(got)])

if __name__ == "__main__":
    unittest.main()
