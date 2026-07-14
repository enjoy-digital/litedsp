#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the chain-glue / bus-I/O / measurement blocks (FIFO, pack, CSR I/O, pattern,
error counter, framing)."""

import unittest

import numpy as np

from migen import Module, run_simulation, passive

from litex.gen import LiteXModule

from litedsp.common              import iq_layout
from litedsp.stream.fifo         import LiteDSPStreamFIFO
from litedsp.stream.adapt        import LiteDSPIQPack, LiteDSPIQUnpack
from litedsp.stream.csr_io       import LiteDSPCSRSource, LiteDSPCSRSink, LiteDSPCSRReader, LiteDSPNullSink
from litedsp.stream.framing      import LiteDSPStreamFramer, LiteDSPStreamDeframer
from litedsp.generation.pattern  import LiteDSPPatternSource, PATTERN_COUNTER, PATTERN_PRBS
from litedsp.analysis.measure    import LiteDSPErrorCounter

from test.common import run_stream, column


def _iq_samples(n, seed=0):
    rng = np.random.RandomState(seed)
    xi  = rng.randint(-2000, 2000, n)
    xq  = rng.randint(-2000, 2000, n)
    return [{"i": int(xi[k]), "q": int(xq[k])} for k in range(n)], xi, xq


class TestStreamFIFO(unittest.TestCase):
    def test_passthrough(self):
        n = 200
        samples, xi, xq = _iq_samples(n, seed=1)
        dut = LiteDSPStreamFIFO(depth=16, data_width=16, with_csr=False)
        cap = run_stream(dut, samples, n, ["i", "q"], ["i", "q"],
            sink_throttle=0.3, source_ready_rate=0.6)
        self.assertTrue(np.array_equal(column(cap, "i", 16), xi))
        self.assertTrue(np.array_equal(column(cap, "q", 16), xq))


class TestIQPackUnpack(unittest.TestCase):
    def test_roundtrip(self):
        ratio, n = 4, 128
        samples, xi, xq = _iq_samples(n, seed=2)

        class Dut(LiteXModule):
            def __init__(self):
                self.pack   = LiteDSPIQPack(ratio=ratio, data_width=16)
                self.unpack = LiteDSPIQUnpack(ratio=ratio, data_width=16)
                self.sink   = self.pack.sink
                self.source = self.unpack.source
                self.comb += self.pack.source.connect(self.unpack.sink)

        cap = run_stream(Dut(), samples, n, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "i", 16), xi))
        self.assertTrue(np.array_equal(column(cap, "q", 16), xq))


class TestPatternSource(unittest.TestCase):
    def test_counter(self):
        dut = LiteDSPPatternSource(data_width=16, with_csr=False)
        # mode defaults to COUNTER; capture a clean ramp.
        cap = run_stream(dut, None, 16, [], ["i"], source_ready_rate=1.0)
        self.assertEqual(column(cap, "i", 16).tolist(), list(range(16)))

    def test_prbs_nonconstant(self):
        dut = LiteDSPPatternSource(data_width=16, seed=0xACE1, with_csr=False)
        def setup():
            yield dut.mode.eq(PATTERN_PRBS)
        cap = run_stream(dut, None, 64, [], ["i"], source_ready_rate=1.0, extra=[setup()])
        vals = column(cap, "i", 16)
        self.assertGreater(len(set(vals.tolist())), 32)   # PRBS visits many distinct values.


class TestCSRSourceSink(unittest.TestCase):
    def test_push_and_count(self):
        n = 8
        class Dut(LiteXModule):
            def __init__(self):
                self.src  = LiteDSPCSRSource(data_width=16, with_csr=False)
                self.snk  = LiteDSPCSRSink(data_width=16, with_csr=False)
                self.comb += self.src.source.connect(self.snk.sink)

        dut = Dut()
        result = {}
        def driver():
            for k in range(n):
                yield dut.src.i.eq(100 + k)
                yield dut.src.q.eq(-k)
                yield dut.src.push.eq(1)
                yield
                yield dut.src.push.eq(0)
                yield
                yield
            result["count"] = (yield dut.snk.count)
            result["last_i"] = (yield dut.snk.last_i)
        run_simulation(dut, [driver()])
        self.assertEqual(result["count"], n)
        self.assertEqual(result["last_i"], 100 + n - 1)


class TestCSRReader(unittest.TestCase):
    def test_paced_readout(self):
        n   = 8
        dut = LiteDSPCSRReader(data_width=16, with_csr=False)
        samples = [{"i": 10*k + 1, "q": -(10*k + 1)} for k in range(n)]
        got = []
        def reader():
            for _ in range(n):
                while not (yield dut.sink.valid):
                    yield
                got.append(((yield dut.sink.i), (yield dut.sink.q)))
                yield dut.pop.eq(1)
                yield
                yield dut.pop.eq(0)
                yield
        from test.common import stream_driver
        run_simulation(dut, [stream_driver(dut.sink, samples, ("i", "q"), throttle=0.3), reader()])
        self.assertEqual(got, [(s["i"], s["q"]) for s in samples])

class TestNullSink(unittest.TestCase):
    def test_counts_all(self):
        n = 50
        samples, _, _ = _iq_samples(n, seed=3)
        dut = LiteDSPNullSink(data_width=16, with_csr=False)
        result = {}
        def feed():
            for s in samples:
                yield dut.sink.i.eq(s["i"]); yield dut.sink.q.eq(s["q"])
                yield dut.sink.valid.eq(1)
                yield
            yield dut.sink.valid.eq(0)
            yield
            result["count"] = (yield dut.count)
        run_simulation(dut, [feed()])
        self.assertEqual(result["count"], n)


class TestErrorCounter(unittest.TestCase):
    def _run(self, ref, rx):
        dut = LiteDSPErrorCounter(data_width=16, with_csr=False)
        out = {}
        @passive
        def drive(ep, samples):
            for s in samples:
                yield ep.i.eq(s[0]); yield ep.q.eq(s[1]); yield ep.valid.eq(1)
                yield
                while (yield ep.ready) == 0:
                    yield
            yield ep.valid.eq(0)
        def checker():
            for _ in range(8*len(ref)):
                yield
            out["errors"] = (yield dut.errors)
            out["total"]  = (yield dut.total)
        run_simulation(dut, [drive(dut.sink_ref, ref), drive(dut.sink_rx, rx), checker()])
        return out

    def test_no_errors(self):
        ref = [(k, -k) for k in range(40)]
        out = self._run(ref, ref)
        self.assertEqual(out["total"], 40)
        self.assertEqual(out["errors"], 0)

    def test_some_errors(self):
        ref = [(k, -k) for k in range(40)]
        rx  = [(k if k % 5 else k + 1, -k) for k in range(40)]   # 8 differ.
        out = self._run(ref, rx)
        self.assertEqual(out["total"], 40)
        self.assertEqual(out["errors"], 8)


class TestFraming(unittest.TestCase):
    def test_framer_marks_boundaries(self):
        length, n = 8, 64
        samples, _, _ = _iq_samples(n, seed=4)
        dut = LiteDSPStreamFramer(length=length, data_width=16, with_csr=False)
        cap = run_stream(dut, samples, n, ["i", "q"], ["i", "q", "first", "last"],
            sink_throttle=0.1, source_ready_rate=0.9)
        last = column(cap, "last")
        first = column(cap, "first")
        self.assertTrue(np.array_equal(np.where(last == 1)[0], np.arange(length - 1, n, length)))
        self.assertTrue(np.array_equal(np.where(first == 1)[0], np.arange(0, n, length)))

    def test_deframer_counts_frames(self):
        length, n = 8, 64
        samples, _, _ = _iq_samples(n, seed=5)
        for k, s in enumerate(samples):
            s["last"] = 1 if (k % length) == (length - 1) else 0
        dut = LiteDSPStreamDeframer(data_width=16, with_csr=False)
        result = {}
        @passive
        def feed():
            for s in samples:
                yield dut.sink.i.eq(s["i"]); yield dut.sink.q.eq(s["q"]); yield dut.sink.last.eq(s["last"])
                yield dut.sink.valid.eq(1)
                yield
                while (yield dut.sink.ready) == 0:
                    yield
            yield dut.sink.valid.eq(0)
        def checker():
            yield dut.source.ready.eq(1)
            for _ in range(4*n):
                yield
            result["frames"] = (yield dut.frames)
        run_simulation(dut, [feed(), checker()])
        self.assertEqual(result["frames"], n // length)


if __name__ == "__main__":
    unittest.main()
