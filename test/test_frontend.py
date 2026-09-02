#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the boundary adapters (litedsp/frontend/)."""

import unittest

from migen import run_simulation, passive

from litex.gen import LiteXModule

from litedsp.frontend.converter import LiteDSPADCInterface, LiteDSPDACInterface, LiteDSPBitstreamInterface
from litedsp.frontend.packet    import LiteDSPIQPacketizer, LiteDSPIQDepacketizer

from test.common import stream_driver, stream_capture

# Converter boundary -------------------------------------------------------------------------------

class TestConverter(unittest.TestCase):
    def _run(self, dut, samples, fields_in, fields_out, n=None):
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, fields_in, throttle=0.2),
            stream_capture(dut.source, cap, n or len(samples), fields_out, ready_rate=0.8),
        ])
        return cap

    def test_adc_offset_binary(self):
        dut = LiteDSPADCInterface(adc_width=12, data_width=16, fmt="offset_binary")
        # Offset-binary 12-bit: 0x000 = -FS, 0x800 = 0, 0xFFF = +FS-1LSB.
        raws = [0x000, 0x800, 0xFFF, 0x801, 0x7FF]
        cap  = self._run(dut, [{"i": r, "q": r ^ 0xFFF} for r in raws], ("i", "q"), ("i", "q"))
        expected = [(r ^ 0x800) - (0x1000 if (r ^ 0x800) & 0x800 else 0) for r in raws]
        for c, e in zip(cap, expected):
            self.assertEqual(c["i"] & 0xFFFF, (e << 4) & 0xFFFF)

    def test_adc_twos(self):
        dut = LiteDSPADCInterface(adc_width=12, data_width=16, fmt="twos")
        raws = [0x000, 0x7FF, 0x800, 0xFFF]                # 0, +max, -min, -1.
        cap  = self._run(dut, [{"i": r, "q": 0} for r in raws], ("i", "q"), ("i", "q"))
        expected = [r - (0x1000 if r & 0x800 else 0) for r in raws]
        for c, e in zip(cap, expected):
            self.assertEqual(c["i"] & 0xFFFF, (e << 4) & 0xFFFF)

    def test_dac_round_trip(self):
        # ADC -> DAC at the same width is identity on the raw codes.
        class Chain(LiteXModule):
            def __init__(self):
                self.adc = LiteDSPADCInterface(adc_width=12, data_width=16, fmt="offset_binary")
                self.dac = LiteDSPDACInterface(dac_width=12, data_width=16, fmt="offset_binary")
                self.sink, self.source = self.adc.sink, self.dac.source
                self.comb += self.adc.source.connect(self.dac.sink)
        dut  = Chain()
        raws = [0x000, 0x123, 0x800, 0xABC, 0xFFF]
        cap  = self._run(dut, [{"i": r, "q": r} for r in raws], ("i", "q"), ("i", "q"))
        for c, r in zip(cap, raws):
            self.assertEqual(c["i"], r)
            self.assertEqual(c["q"], r)

# Host-link packetizing ----------------------------------------------------------------------------

class TestPacket(unittest.TestCase):
    def test_packetizer_words_and_last(self):
        # ratio=2 (64-bit words), 4 samples/packet -> 2 words/packet, last on every 2nd word.
        dut = LiteDSPIQPacketizer(data_width=16, word_width=64, samples_per_packet=4, with_csr=False)
        samples = [{"i": k + 1, "q": -(k + 1)} for k in range(8)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, 4, ("data", "last"), ready_rate=0.8),
        ])
        mask = 0xFFFF
        for w, c in enumerate(cap):
            s0, s1 = samples[2*w], samples[2*w + 1]
            word = (s0["i"] & mask) | (s0["q"] & mask) << 16 \
                 | (s1["i"] & mask) << 32 | (s1["q"] & mask) << 48
            self.assertEqual(c["data"], word)
            self.assertEqual(c["last"], int(w % 2 == 1))

    def test_depacketizer_round_trip(self):
        class Loop(LiteXModule):
            def __init__(self):
                self.pk  = LiteDSPIQPacketizer(data_width=16, word_width=64, samples_per_packet=4,
                    with_csr=False)
                self.dpk = LiteDSPIQDepacketizer(data_width=16, word_width=64, with_csr=False)
                self.sink, self.source = self.pk.sink, self.dpk.source
                self.comb += self.pk.source.connect(self.dpk.sink)
        dut = Loop()
        samples = [{"i": 3*k + 1, "q": -(3*k + 1)} for k in range(8)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, len(samples), ("i", "q"), ready_rate=0.8),
        ])
        mask = 0xFFFF
        for s, c in zip(samples, cap):
            self.assertEqual((c["i"] & mask, c["q"] & mask), (s["i"] & mask, s["q"] & mask))

# UDP streamer (LiteEth glue) ----------------------------------------------------------------------

class TestUDP(unittest.TestCase):
    def test_streamer_emits_udp_packets(self):
        from liteeth.core.udp import LiteEthUDPUserPort
        port = LiteEthUDPUserPort(32)
        from litedsp.frontend.udp import LiteDSPUDPIQStreamer
        dut = LiteDSPUDPIQStreamer(port, ip_address="192.168.1.100", udp_port=6000,
            data_width=16, word_width=32, samples_per_packet=4, with_csr=False)
        samples = [{"i": k + 1, "q": k + 101} for k in range(8)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.1),
            stream_capture(port.sink, cap, 8, ("data", "last", "dst_port", "length"),
                ready_rate=0.9),
        ])
        for w, c in enumerate(cap):
            s = samples[w]
            self.assertEqual(c["data"], (s["i"] & 0xFFFF) | (s["q"] & 0xFFFF) << 16)
            self.assertEqual(c["last"], int(w % 4 == 3))
            self.assertEqual(c["dst_port"], 6000)
        self.assertEqual(cap[3]["length"], 16)             # 4 samples x 4 bytes.

    def test_receiver_round_trip(self):
        from liteeth.core.udp import LiteEthUDPUserPort
        from litedsp.frontend.udp import LiteDSPUDPIQReceiver

        port = LiteEthUDPUserPort(32)
        dut  = LiteDSPUDPIQReceiver(port, udp_port=6000, data_width=16, word_width=32, with_csr=False)
        samples = [(5*k + 1, 5*k + 2) for k in range(8)]
        words   = [{"data": (i & 0xFFFF) | (q & 0xFFFF) << 16, "last": int(k % 4 == 3),
                    "dst_port": 6000} for k, (i, q) in enumerate(samples)]
        cap = []
        run_simulation(dut, [
            stream_driver(port.source, words, ("data", "last", "dst_port"), throttle=0.1),
            stream_capture(dut.source, cap, len(samples), ("i", "q"), ready_rate=0.8),
        ])
        for (i, q), c in zip(samples, cap):
            self.assertEqual((c["i"], c["q"]), (i, q))

if __name__ == "__main__":
    unittest.main()

# Bitstream interface ------------------------------------------------------------------------------

class TestBitstreamInterface(unittest.TestCase):
    def run_iface(self, patterns, clock_div=8, dual_edge=False, ready_rate=1.0, n_bits=64):
        """Drive modulator-like data (launched on mclk edges) and capture every 1-bit source."""
        n_lines = len(patterns)
        dut = LiteDSPBitstreamInterface(clock_div=clock_div,
            n_channels=2*n_lines if dual_edge else n_lines, dual_edge=dual_edge)
        caps = [[] for _ in dut.sources]
        flags = []

        @passive
        def modulator():
            # A modulator launches its bit right after the mclk rising edge (and, for a dual-edge
            # stereo microphone, the second channel after the falling edge); runs until the
            # captures are done.
            prev, idx = 0, [0]*n_lines
            while True:
                clk = (yield dut.mclk)
                if clk != prev:
                    for line in range(n_lines):
                        edge_bits = patterns[line]
                        if dual_edge:
                            bit = edge_bits[idx[line] % len(edge_bits)]
                            idx[line] += 1
                        elif clk:                            # Rising edge only.
                            bit = edge_bits[idx[line] % len(edge_bits)]
                            idx[line] += 1
                        else:
                            continue
                        cur = (yield dut.mdat)
                        yield dut.mdat.eq((cur & ~(1 << line)) | (bit << line))
                prev = clk
                yield

        @passive
        def watch():
            while True:
                flags.append((yield dut.overrun))
                yield

        gens = [modulator(), watch()] + [stream_capture(src, cap, n_bits, ["data"],
            ready_rate=ready_rate) for src, cap in zip(dut.sources, caps)]
        run_simulation(dut, gens)
        return flags[-1], [[c["data"] for c in cap] for cap in caps]

    def test_single_edge_sequence(self):
        pattern = [1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0]
        overrun, caps = self.run_iface([pattern])
        # The stream reproduces the pattern (from wherever the capture started), no overrun.
        self.assertIn("".join(map(str, pattern*2)), "".join(map(str, caps[0])))
        self.assertEqual(overrun, 0)

    def test_overrun_flag(self):
        # A consumer slower than the bit rate loses bits and latches the sticky overrun flag.
        overrun, _ = self.run_iface([[1, 0, 1, 1]], clock_div=4, ready_rate=0.1, n_bits=8)
        self.assertEqual(overrun, 1)

    def test_dual_edge_two_channels(self):
        pattern = [1, 0, 0, 1, 1, 1, 0, 1]                 # L, R, L, R, ... on one line.
        _, caps = self.run_iface([pattern], dual_edge=True)
        left, right = pattern[0::2], pattern[1::2]
        for got, ref in ((caps[0], left), (caps[1], right)):
            self.assertIn("".join(map(str, ref*3)), "".join(map(str, got)))

    def test_invalid(self):
        for kwargs in ({"clock_div": 3}, {"clock_div": 6, "n_channels": 3, "dual_edge": True},
                       {"n_channels": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPBitstreamInterface(**kwargs)
