#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for timestamped streams (litedsp/stream/timestamp.py + packetizer header).

Covers the TimeCore (set/latch/PPS/IRQ), the edge taggers, the timestamped packet header
round-trip, and the model's acceptance criterion: a tagged burst crosses a time-agnostic
gain -> FIR chain and the host recovers every sample's absolute ingress time exactly
(egress_time - sum(latency) == ingress_time + k), with no time threaded through the blocks.
"""

import unittest

from migen import *

from migen import run_simulation, passive

from litex.gen import LiteXModule

from litedsp.common           import TIMESTAMP_WIDTH, time_param_layout
from litedsp.filter.fir       import LiteDSPFIRFilterComplex
from litedsp.level.gain       import LiteDSPGain
from litedsp.stream.timestamp import LiteDSPTimeCore, LiteDSPTimestamper, LiteDSPTimeUntagger
from litedsp.frontend.packet  import (LiteDSPIQPacketizer, LiteDSPIQDepacketizer,
    TIMESTAMP_MAGIC, TIMESTAMP_VERSION)
from litedsp.software.drivers import TimeCoreDriver

from litedsp.flow import registry as flow_registry

from test.common import stream_driver, stream_capture
from test.models import timestamper_model

# Helpers ------------------------------------------------------------------------------------------

@passive
def watch_transfers(endpoint, count, times, firsts=None):
    """Record ``count`` at every endpoint transfer (and optionally the first flags)."""
    while True:
        if (yield endpoint.valid) and (yield endpoint.ready):
            times.append((yield count))
            if firsts is not None:
                firsts.append((yield endpoint.first))
        yield

# Time Core ----------------------------------------------------------------------------------------

class TestTimeCore(unittest.TestCase):
    def test_count_set_latch(self):
        dut = LiteDSPTimeCore(with_csr=False)

        def gen():
            # Free-running: +1 per cycle.
            for _ in range(5):
                yield
            c0 = (yield dut.count)
            yield
            self.assertEqual((yield dut.count), c0 + 1)
            # Set: counter continues from the written value. (Generator writes become visible
            # to the sync logic one cycle after the eq(), hence the extra yields.)
            yield dut.set_value.eq(1000)
            yield dut.set_stb.eq(1)
            yield
            yield dut.set_stb.eq(0)
            yield
            self.assertEqual((yield dut.count), 1000)
            yield
            self.assertEqual((yield dut.count), 1001)
            # Latch: frozen while the counter keeps running (atomic multi-word read).
            yield dut.latch.eq(1)
            yield
            latched = (yield dut.count)                    # count during the latch cycle.
            yield dut.latch.eq(0)
            yield
            self.assertEqual((yield dut.latched), latched)
            for _ in range(4):
                yield
            self.assertEqual((yield dut.latched), latched)
            self.assertEqual((yield dut.count), latched + 5)

        run_simulation(dut, [gen()])

    def test_pps_latches_count(self):
        dut = LiteDSPTimeCore(with_csr=False)

        def pulse(width=3):
            yield dut.pps.eq(1)
            yield                                          # PPS visible to logic this cycle.
            at_edge = (yield dut.count)                    # count latched at the rising edge.
            yield
            for _ in range(width - 1):                     # Level-held PPS: edge only.
                yield
            yield dut.pps.eq(0)
            yield
            return at_edge

        def gen():
            for _ in range(10):
                yield
            t0 = yield from pulse()
            self.assertEqual((yield dut.pps_time), t0)
            for _ in range(20):
                yield
            self.assertEqual((yield dut.pps_time), t0)     # Stable between pulses.
            t1 = yield from pulse()
            self.assertEqual((yield dut.pps_time), t1)
            self.assertGreater(t1, t0)

        run_simulation(dut, [gen()])

    def test_pps_irq(self):
        dut = LiteDSPTimeCore(with_csr=False, with_irq=True)

        def gen():
            for _ in range(4):
                yield
            self.assertEqual((yield dut.ev.pps.pending), 0)
            yield dut.pps.eq(1)
            yield
            yield dut.pps.eq(0)
            for _ in range(4):
                yield
            self.assertEqual((yield dut.ev.pps.pending), 1)

        run_simulation(dut, [gen()])

    def test_csr_names(self):
        dut   = LiteDSPTimeCore(with_csr=True)
        names = {csr.name for csr in dut.get_csrs()}
        self.assertTrue({"set_time", "latch", "time", "pps_time"} <= names, names)

# Timestamper / Untagger ---------------------------------------------------------------------------

class _TaggerDUT(LiteXModule):
    """TimeCore + Timestamper (the parent-connection pattern from doc/timestamps.md)."""
    def __init__(self, data_width=16, stream_id=0):
        self.time_core   = LiteDSPTimeCore(with_csr=False)
        self.timestamper = LiteDSPTimestamper(data_width=data_width, stream_id=stream_id,
            with_csr=False)
        self.sink, self.source = self.timestamper.sink, self.timestamper.source
        self.comb += self.timestamper.time.eq(self.time_core.count)

class TestTimestamper(unittest.TestCase):
    def _run(self, samples, fields_in, throttle=0.3, ready_rate=0.7):
        dut   = _TaggerDUT(stream_id=0x42)
        cap   = []
        times = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, fields_in, throttle=throttle),
            stream_capture(dut.source, cap, len(samples),
                ("i", "q", "timestamp", "stream_id"), ready_rate=ready_rate),
            watch_transfers(dut.sink, dut.time_core.count, times),
        ])
        return cap, times

    def test_unframed_tags_every_sample(self):
        # No framing: each sample carries its own ingress (acceptance) time.
        samples = [{"i": k, "q": -k} for k in range(16)]
        cap, times = self._run(samples, ("i", "q"))
        self.assertEqual([c["timestamp"] for c in cap], timestamper_model(times))
        self.assertEqual([c["timestamp"] for c in cap], times)
        for c, s in zip(cap, samples):
            self.assertEqual((c["i"], c["q"]), (s["i"], s["q"]))  # Signed passthrough.
            self.assertEqual(c["stream_id"], 0x42)

    def test_framed_tags_on_first(self):
        # Framed: the tag latches at each frame first and holds for the whole frame.
        frame_len = 4
        samples = [{"i": k, "q": 0,
                    "first": int(k % frame_len == 0),
                    "last":  int(k % frame_len == frame_len - 1)} for k in range(12)]
        cap, times = self._run(samples, ("i", "q", "first", "last"))
        first = [s["first"] for s in samples]
        last  = [s["last"]  for s in samples]
        self.assertEqual([c["timestamp"] for c in cap], timestamper_model(times, first, last))
        for f in range(len(samples)//frame_len):           # Constant within each frame.
            tags = {cap[k]["timestamp"] for k in range(f*frame_len, (f + 1)*frame_len)}
            self.assertEqual(tags, {times[f*frame_len]})

    def test_untagger_strips_params(self):
        class Loop(LiteXModule):
            def __init__(self):
                self.tag   = _TaggerDUT()
                self.untag = LiteDSPTimeUntagger()
                self.sink, self.source = self.tag.sink, self.untag.source
                self.comb += self.tag.source.connect(self.untag.sink)
        dut = Loop()
        self.assertEqual([f[0] for f in dut.source.description.payload_layout], ["i", "q"])
        self.assertEqual(dut.source.description.param_layout, [])
        samples = [{"i": 3*k, "q": 5 - k} for k in range(8)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, len(samples), ("i", "q"), ready_rate=0.8),
        ])
        mask = 0xFFFF
        for c, s in zip(cap, samples):
            self.assertEqual((c["i"] & mask, c["q"] & mask), (s["i"] & mask, s["q"] & mask))

# Absolute-time recovery across a time-agnostic chain (acceptance test) -----------------------------

class _Chain(LiteXModule):
    """timestamper -> gain -> FIR -> timestamper: no time threaded through the DSP blocks."""
    def __init__(self, data_width=16):
        self.time_core = LiteDSPTimeCore(with_csr=False)
        self.ts_in     = LiteDSPTimestamper(data_width=data_width, with_csr=False)
        self.gain      = LiteDSPGain(data_width=data_width, with_csr=False)
        self.fir       = LiteDSPFIRFilterComplex(n_taps=4, data_width=data_width,
            coefficients=[16384, 0, 0, 0], with_csr=False)  # 0.5 impulse: alignment-preserving.
        self.ts_out    = LiteDSPTimestamper(data_width=data_width, with_csr=False)
        self.sink, self.source = self.ts_in.sink, self.ts_out.source
        self.comb += [
            self.ts_in.time.eq(self.time_core.count),
            self.ts_out.time.eq(self.time_core.count),
            # Strip the tags at the chain boundary: the DSP blocks are plain I/Q.
            self.ts_in.source.connect(self.gain.sink, omit={"timestamp", "stream_id"}),
            self.gain.source.connect(self.fir.sink),
            self.fir.source.connect(self.ts_out.sink),
        ]

class TestTimeRecovery(unittest.TestCase):
    def test_burst_time_recovered_exactly(self):
        # A tagged burst crosses gain -> FIR (neither carries time). The host recovers each
        # output sample's absolute ingress time from the egress tag and the declared
        # BlockSpec latencies: ingress_time(k) = egress_tag(k) - sum(latency) == t0 + k.
        dut = _Chain()
        n   = 32
        samples = [{"i": 100 + k, "q": -k, "first": int(k == 0)} for k in range(n)]
        cap, in_times, in_firsts = [], [], []
        run_simulation(dut, [
            # Free flow: 1 sample/cycle, so sample index == cycle delta (see doc/timestamps.md).
            stream_driver(dut.sink, samples, ("i", "q", "first"), throttle=0.0),
            stream_capture(dut.source, cap, n, ("i", "q", "timestamp"), ready_rate=1.0),
            watch_transfers(dut.ts_in.sink, dut.time_core.count, in_times, in_firsts),
        ])
        # The burst's ingress tag (what a host would get from the packet header).
        self.assertEqual(in_firsts[0], 1)
        t0 = in_times[0]
        # Per-block latency comes from the reflected BlockSpec (same source as self.latency).
        palette = flow_registry.registry()
        total   = palette["gain"].latency + palette["fir_complex"].latency
        self.assertEqual(total, dut.gain.latency + dut.fir.latency)
        for k, c in enumerate(cap):
            recovered = c["timestamp"] - total
            self.assertEqual(recovered, t0 + k)            # +-0 samples.
            self.assertEqual(recovered, in_times[k])       # == actual acceptance time.
        # Payload sanity: 0.5 impulse FIR halves the (unity-gain) samples, round half up.
        for k, c in enumerate(cap):
            self.assertEqual(c["i"], (100 + k + 1) >> 1)

# Timestamped packet header -------------------------------------------------------------------------

class _PacketDUT(LiteXModule):
    def __init__(self, samples_per_packet=4, stream_id=0xAB, with_depacketizer=False):
        self.time_core = LiteDSPTimeCore(with_csr=False)
        self.pk = LiteDSPIQPacketizer(data_width=16, word_width=32,
            samples_per_packet=samples_per_packet, with_timestamp=True, stream_id=stream_id,
            with_csr=False)
        self.comb += self.pk.time.eq(self.time_core.count)
        self.sink = self.pk.sink
        if with_depacketizer:
            self.dpk = LiteDSPIQDepacketizer(data_width=16, word_width=32,
                with_timestamp=True, with_csr=False)
            self.comb += self.pk.source.connect(self.dpk.sink)
            self.source = self.dpk.source
        else:
            self.source = self.pk.source

@passive
def watch_packet_arrivals(pk, count, times):
    """Record ``count`` when each packet's first sample arrives at the packing stage."""
    armed = True
    while True:
        v = (yield pk.framer.source.valid)
        r = (yield pk.framer.source.ready)
        f = (yield pk.framer.source.first)
        l = (yield pk.framer.source.last)
        t = (yield count)
        if armed and v and f:
            times.append(t)
            armed = False
        if v and r and l:
            armed = True
        yield

class TestPacketTimestamp(unittest.TestCase):
    def test_header_layout_and_last(self):
        # 32-bit words, 4 samples/packet: 4 header words + 4 payload words per packet.
        spp = 4
        dut = _PacketDUT(samples_per_packet=spp, stream_id=0xAB)
        samples = [{"i": k + 1, "q": -(k + 1)} for k in range(2*spp)]
        cap, arrivals = [], []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, 16, ("data", "first", "last"), ready_rate=0.8),
            watch_packet_arrivals(dut.pk, dut.time_core.count, arrivals),
        ])
        mask = 0xFFFF
        for p in range(2):                                 # Two packets.
            hdr = cap[8*p:8*p + 4]
            pld = cap[8*p + 4:8*p + 8]
            self.assertEqual(hdr[0]["data"] & 0xFF, TIMESTAMP_MAGIC)
            self.assertEqual((hdr[0]["data"] >> 8) & 0xFF, TIMESTAMP_VERSION)
            self.assertEqual((hdr[0]["data"] >> 16) & 0xFF, 0xAB)
            self.assertEqual(hdr[1]["data"], spp)          # Sample count.
            timestamp = hdr[2]["data"] | (hdr[3]["data"] << 32)
            self.assertEqual(timestamp, arrivals[p])       # First-sample ingress time.
            self.assertEqual([w["first"] for w in cap[8*p:8*p + 8]], [1] + [0]*7)
            self.assertEqual([w["last"] for w in cap[8*p:8*p + 8]], [0]*7 + [1])
            for k, w in enumerate(pld):                    # Payload untouched, LSB = I.
                s = samples[spp*p + k]
                self.assertEqual(w["data"], (s["i"] & mask) | (s["q"] & mask) << 16)

    def test_round_trip_preserves_timestamp_and_stream_id(self):
        spp = 4
        dut = _PacketDUT(samples_per_packet=spp, stream_id=0x5C, with_depacketizer=True)
        samples = [{"i": 7*k + 1, "q": -(7*k + 1)} for k in range(3*spp)]
        cap, arrivals = [], []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, len(samples),
                ("i", "q", "timestamp", "stream_id", "first", "last"), ready_rate=0.7),
            watch_packet_arrivals(dut.pk, dut.time_core.count, arrivals),
        ])
        mask = 0xFFFF
        for k, (c, s) in enumerate(zip(cap, samples)):
            p = k//spp
            self.assertEqual((c["i"] & mask, c["q"] & mask), (s["i"] & mask, s["q"] & mask))
            self.assertEqual(c["stream_id"], 0x5C)
            self.assertEqual(c["timestamp"], arrivals[p])  # All samples carry the packet tag.
            self.assertEqual(c["first"], int(k % spp == 0))
            self.assertEqual(c["last"], int(k % spp == spp - 1))

    def test_legacy_format_bit_identical(self):
        # with_timestamp off (default): exactly today's headerless words, last every packet.
        dut = LiteDSPIQPacketizer(data_width=16, word_width=32, samples_per_packet=4,
            with_csr=False)
        samples = [{"i": k + 1, "q": k + 101} for k in range(8)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, 8, ("data", "last"), ready_rate=0.8),
        ])
        for w, c in enumerate(cap):
            s = samples[w]
            self.assertEqual(c["data"], (s["i"] & 0xFFFF) | (s["q"] & 0xFFFF) << 16)
            self.assertEqual(c["last"], int(w % 4 == 3))

# TimeCore driver ------------------------------------------------------------------------------------

class _MockCSR:
    def __init__(self, value=0):
        self.value  = value
        self.writes = []

    def read(self):
        return self.value

    def write(self, value):
        self.writes.append(value)
        self.value = value

class _MockRegs:
    pass

class _MockBus:
    def __init__(self, regs):
        self.regs = _MockRegs()
        for name, csr in regs.items():
            setattr(self.regs, name, csr)

class TestTimeCoreDriver(unittest.TestCase):
    def test_read_set_pps(self):
        bus = _MockBus({f"tc_{r}": _MockCSR() for r in TimeCoreDriver.regs})
        tc  = TimeCoreDriver(bus, "tc")
        bus.regs.tc_time.value = 123456789
        self.assertEqual(tc.read_time(), 123456789)
        self.assertEqual(bus.regs.tc_latch.writes, [1])    # Latch before read (atomicity).
        tc.set(1 << 40)
        self.assertEqual(bus.regs.tc_set_time.writes, [1 << 40])
        bus.regs.tc_pps_time.value = 987654321
        self.assertEqual(tc.read_pps_time(), 987654321)

if __name__ == "__main__":
    unittest.main()
