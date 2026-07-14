#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the multi-sample-per-cycle (parallel) datapaths.

Each parallel block must be bit-identical to its serial counterpart on the flattened lane
stream — the references are the same NumPy models used by the serial tests.
"""

import random
import unittest

import numpy as np

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.stream.adapt           import LiteDSPIQSerialToParallel, LiteDSPIQParallelToSerial
from litedsp.generation.nco_parallel import LiteDSPParallelNCO
from litedsp.mixing.mixer_parallel  import LiteDSPParallelMixer
from litedsp.mixing.ddc_parallel    import LiteDSPParallelDDC
from litedsp.filter.fir_parallel    import LiteDSPParallelFIRFilter, LiteDSPParallelFIRFilterComplex
from litedsp.filter.cic_parallel    import LiteDSPParallelCICDecimator

from test.common import stream_driver, stream_capture, to_signed
from test.models import (nco_model, mixer_model, fir_model, fir_complex_model,
    cic_decimator_model)

# Helpers ------------------------------------------------------------------------------------------

def pack_lanes(values, data_width=16):
    """Pack per-lane integers into one multi-sample field (lane 0 in the LSBs)."""
    mask = (1 << data_width) - 1
    word = 0
    for k, v in enumerate(values):
        word |= (int(v) & mask) << (k*data_width)
    return word

def unpack_lanes(word, n_samples, data_width=16):
    """Inverse of :func:`pack_lanes`, sign-extending each lane."""
    mask = (1 << data_width) - 1
    return [to_signed([(word >> (k*data_width)) & mask], data_width)[0] for k in range(n_samples)]

def flatten(captured, field, n_samples, data_width=16):
    out = []
    for c in captured:
        out += unpack_lanes(c[field], n_samples, data_width)
    return np.array(out)

# Serial <-> Parallel adapters ---------------------------------------------------------------------

class TestSerialParallelAdapters(unittest.TestCase):
    def test_round_trip(self):
        n_samples = 4
        class Loop(LiteXModule):
            def __init__(self):
                self.s2p = LiteDSPIQSerialToParallel(n_samples=n_samples, data_width=16)
                self.p2s = LiteDSPIQParallelToSerial(n_samples=n_samples, data_width=16)
                self.sink, self.source = self.s2p.sink, self.p2s.source
                self.comb += self.s2p.source.connect(self.p2s.sink)
        dut  = Loop()
        prng = random.Random(0)
        samples = [{"i": prng.randint(-30000, 30000), "q": prng.randint(-30000, 30000)}
                   for _ in range(32)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, len(samples), ("i", "q"), ready_rate=0.7),
        ])
        for s, c in zip(samples, cap):
            self.assertEqual((to_signed([c["i"]], 16)[0], to_signed([c["q"]], 16)[0]),
                             (s["i"], s["q"]))

    def test_lane_order(self):
        n_samples = 2
        dut = LiteDSPIQSerialToParallel(n_samples=n_samples, data_width=16)
        samples = [{"i": k + 1, "q": 0} for k in range(8)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q")),
            stream_capture(dut.source, cap, 4, ("i", "q")),
        ])
        for b, c in enumerate(cap):
            self.assertEqual(unpack_lanes(c["i"], n_samples), [2*b + 1, 2*b + 2])

# Parallel NCO -------------------------------------------------------------------------------------

class TestParallelNCO(unittest.TestCase):
    def test_matches_serial_model(self):
        n_samples, n_beats = 4, 32
        phase_inc = 0x0891_2345
        dut = LiteDSPParallelNCO(n_samples=n_samples, data_width=16, with_csr=False)
        dut.phase_inc.reset = phase_inc
        cap = []
        run_simulation(dut, [stream_capture(dut.source, cap, n_beats, ("i", "q"), ready_rate=0.7)])
        gi = flatten(cap, "i", n_samples)
        gq = flatten(cap, "q", n_samples)
        ri, rq = nco_model(phase_inc, n_samples*n_beats)
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

# Parallel Mixer -----------------------------------------------------------------------------------

class TestParallelMixer(unittest.TestCase):
    def test_matches_model(self):
        n_samples, n = 2, 64                              # 64 beats = 128 samples.
        prng = random.Random(1)
        a = [(prng.randint(-20000, 20000), prng.randint(-20000, 20000)) for _ in range(n_samples*n)]
        b = [(prng.randint(-20000, 20000), prng.randint(-20000, 20000)) for _ in range(n_samples*n)]
        def beats(x):
            return [{"i": pack_lanes([s[0] for s in x[k:k + n_samples]]),
                     "q": pack_lanes([s[1] for s in x[k:k + n_samples]])}
                    for k in range(0, len(x), n_samples)]
        dut = LiteDSPParallelMixer(n_samples=n_samples, data_width=16, with_csr=False)  # mode=0: down.
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink_a, beats(a), ("i", "q"), throttle=0.2),
            stream_driver(dut.sink_b, beats(b), ("i", "q"), throttle=0.3, seed=7),
            stream_capture(dut.source, cap, n, ("i", "q"), ready_rate=0.7),
        ])
        gi = flatten(cap, "i", n_samples)
        gq = flatten(cap, "q", n_samples)
        ri, rq = mixer_model(np.array([s[0] for s in a]), np.array([s[1] for s in a]),
                             np.array([s[0] for s in b]), np.array([s[1] for s in b]), mode="down")
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

# Parallel FIR -------------------------------------------------------------------------------------

class TestParallelFIR(unittest.TestCase):
    def test_matches_model(self):
        for n_samples in (2, 4):
            n_taps, n_beats = 7, 48
            prng   = random.Random(2)
            coeffs = [prng.randint(-8000, 8000) for _ in range(n_taps)]
            x      = [prng.randint(-20000, 20000) for _ in range(n_samples*n_beats)]
            dut = LiteDSPParallelFIRFilter(n_samples=n_samples, n_taps=n_taps, data_width=16)
            for t in range(n_taps):
                dut.coeffs[t].reset = coeffs[t]           # Signed; do not mask.
            beats = [{"data": pack_lanes(x[k:k + n_samples])}
                     for k in range(0, len(x), n_samples)]
            cap = []
            run_simulation(dut, [
                stream_driver(dut.sink, beats, ("data",), throttle=0.2),
                stream_capture(dut.source, cap, n_beats, ("data",), ready_rate=0.7),
            ])
            got = flatten(cap, "data", n_samples)
            ref = fir_model(np.array(x), coeffs)[:len(got)]
            self.assertTrue(np.array_equal(got, ref), f"n_samples={n_samples}")

class TestParallelFIRComplex(unittest.TestCase):
    def test_matches_model(self):
        n_samples, n_taps, n_beats = 2, 7, 48
        prng   = random.Random(3)
        coeffs = [prng.randint(-8000, 8000) for _ in range(n_taps)]
        x      = [(prng.randint(-20000, 20000), prng.randint(-20000, 20000))
                  for _ in range(n_samples*n_beats)]
        dut = LiteDSPParallelFIRFilterComplex(n_samples=n_samples, n_taps=n_taps, data_width=16,
            coefficients=coeffs, with_csr=False)
        beats = [{"i": pack_lanes([s[0] for s in x[k:k + n_samples]]),
                  "q": pack_lanes([s[1] for s in x[k:k + n_samples]])}
                 for k in range(0, len(x), n_samples)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, beats, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, n_beats, ("i", "q"), ready_rate=0.7),
        ])
        gi = flatten(cap, "i", n_samples)
        gq = flatten(cap, "q", n_samples)
        ri, rq = fir_complex_model([s[0] for s in x], [s[1] for s in x], coeffs)
        self.assertTrue(np.array_equal(gi, ri[:len(gi)]))
        self.assertTrue(np.array_equal(gq, rq[:len(gq)]))

# Parallel CIC -------------------------------------------------------------------------------------

class TestParallelCIC(unittest.TestCase):
    def test_matches_model(self):
        for n_samples, R in ((2, 8), (4, 8), (4, 4)):
            N, n_beats = 3, 128
            prng = random.Random(4)
            x    = [(prng.randint(-20000, 20000), prng.randint(-20000, 20000))
                    for _ in range(n_samples*n_beats)]
            dut  = LiteDSPParallelCICDecimator(n_samples=n_samples, data_width=16, decimation=R, n_stages=N,
                with_csr=False)
            beats = [{"i": pack_lanes([s[0] for s in x[k:k + n_samples]]),
                      "q": pack_lanes([s[1] for s in x[k:k + n_samples]])}
                     for k in range(0, len(x), n_samples)]
            n_out = n_samples*n_beats//R - 2
            cap = []
            run_simulation(dut, [
                stream_driver(dut.sink, beats, ("i", "q"), throttle=0.2),
                stream_capture(dut.source, cap, n_out, ("i", "q"), ready_rate=0.7),
            ])
            gi = np.array(to_signed([c["i"] for c in cap], 16))
            gq = np.array(to_signed([c["q"] for c in cap], 16))
            ri = cic_decimator_model(np.array([s[0] for s in x]), R, N)[:n_out]
            rq = cic_decimator_model(np.array([s[1] for s in x]), R, N)[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"n={n_samples} R={R}")
            self.assertTrue(np.array_equal(gq, rq), f"n={n_samples} R={R}")

# Parallel DDC -------------------------------------------------------------------------------------

class TestParallelDDC(unittest.TestCase):
    def test_matches_model_chain(self):
        n_samples, R, N, n_beats = 4, 8, 3, 128
        phase_inc = 0x0913_579B
        prng = random.Random(5)
        x    = [(prng.randint(-20000, 20000), prng.randint(-20000, 20000))
                for _ in range(n_samples*n_beats)]
        dut = LiteDSPParallelDDC(n_samples=n_samples, data_width=16, decimation=R, cic_stages=N,
            with_csr=False)
        dut.nco.phase_inc.reset = phase_inc
        beats = [{"i": pack_lanes([s[0] for s in x[k:k + n_samples]]),
                  "q": pack_lanes([s[1] for s in x[k:k + n_samples]])}
                 for k in range(0, len(x), n_samples)]
        n_out = n_samples*n_beats//R - 2
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, beats, ("i", "q"), throttle=0.2),
            stream_capture(dut.source, cap, n_out, ("i", "q"), ready_rate=0.7),
        ])
        gi = np.array(to_signed([c["i"] for c in cap], 16))
        gq = np.array(to_signed([c["q"] for c in cap], 16))
        # Exact model chain: NCO -> complex down-mix -> CIC.
        lo_i, lo_q = nco_model(phase_inc, len(x))
        mi, mq = mixer_model(np.array([s[0] for s in x]), np.array([s[1] for s in x]),
                             lo_i, lo_q, mode="down")
        ri = cic_decimator_model(mi, R, N)[:n_out]
        rq = cic_decimator_model(mq, R, N)[:n_out]
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

if __name__ == "__main__":
    unittest.main()
