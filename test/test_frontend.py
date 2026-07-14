#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the boundary adapters (litedsp/frontend/)."""

import unittest

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.frontend.converter import LiteDSPADCInterface, LiteDSPDACInterface
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
