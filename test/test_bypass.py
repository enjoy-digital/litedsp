#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Bypass contract: with ``bypass`` set, every bypass-capable block is an exact passthrough."""

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.flow import registry
from litedsp.filter.fir import LiteDSPFIRFilterComplex
from litedsp.flow.metadata import _accepts_with_csr

from test.common import run_stream, column

# Blocks with a boolean ``bypass`` control (the mixer's 2-bit input-select bypass is tested
# in test_mixer.py; the capture scope's bypass in test_capture.py).
BYPASS_BLOCKS = [
    "gain", "fir_real", "fir_complex", "cfr", "clipper", "saturate", "dc_offset", "iq_balance",
    "dc_blocker", "dc_blocker_real", "mti", "tvg", "threshold", "pixel_gain", "pixel_lut", "gamma",
    "color_matrix", "box_overlay", "convolutional_interleaver", "convolutional_deinterleaver",
    "moving_average", "iir_biquad", "notch", "comb_filter", "allpass", "dpd",
    "slew_limiter", "volume", "stereo_matrix", "dither", "audio_eq", "compressor", "delay_line",
]

class TestBypass(unittest.TestCase):
    def test_identity(self):
        reg  = registry.registry()
        prng = random.Random(1)
        for key in BYPASS_BLOCKS:
            with self.subTest(block=key):
                spec   = reg[key]
                kwargs = dict(spec.kwargs)
                if _accepts_with_csr(spec.cls):
                    kwargs["with_csr"] = False
                dut = spec.cls(**kwargs)
                self.assertTrue(hasattr(dut, "bypass"), f"{key} has no bypass")
                dut.bypass.reset = 1
                # Every payload field: signed fields get random samples, an unsigned tag (the
                # TDM ``channel``) cycles through its range so tagged streams are covered too.
                shapes = {name: shape for name, shape, *_ in dut.sink.description.payload_layout}
                fields = list(shapes)
                data   = []
                for k in range(80):
                    beat = {}
                    for f in fields:
                        width, signed = (shapes[f] if isinstance(shapes[f], tuple)
                                         else (shapes[f], False))
                        lim     = min(30000, 2**(width - 1) - 1) if signed else 2**width - 1
                        beat[f] = prng.randint(-lim, lim) if signed else k % (lim + 1)
                    data.append(beat)
                cap = run_stream(dut, data, len(data), fields, fields,
                    sink_throttle=0.2, source_ready_rate=0.7)
                for f in fields:
                    width, signed = (shapes[f] if isinstance(shapes[f], tuple)
                                     else (shapes[f], False))
                    got = column(cap, f, width if signed else None)
                    self.assertTrue(np.array_equal(got, [d[f] for d in data]),
                        f"{key}: {f} not passed through under bypass")

    def test_fir_complex_switch_under_traffic(self):
        # Toggle bypass while a free-flowing stream runs: every beat keeps its order and the
        # processing latency, filtered (tap 0.5) or passed through as selected at its input.
        for architecture in ("classic", "pipelined"):
            with self.subTest(architecture=architecture):
                dut = LiteDSPFIRFilterComplex(n_taps=4, coefficients=[16384, 0, 0, 0],
                    architecture=architecture, with_csr=False)
                ins, outs = [], []
                def gen():
                    n = 1
                    yield dut.source.ready.eq(1)
                    for cycle in range(60):
                        bypass = int(8 <= cycle < 14 or 20 <= cycle < 21)
                        yield dut.bypass.eq(bypass)
                        yield dut.sink.valid.eq(int(n <= 40))
                        yield dut.sink.i.eq(100*n)
                        yield dut.sink.q.eq(-100*n)
                        yield
                        if (yield dut.sink.valid) and (yield dut.sink.ready):
                            ins.append((cycle, n, bypass))
                            n += 1
                        if (yield dut.source.valid) and (yield dut.source.ready):
                            outs.append((cycle, (yield dut.source.i), (yield dut.source.q)))
                run_simulation(dut, gen())
                self.assertEqual(len(outs), len(ins))
                for (c_in, n, bypass), (c_out, i, q) in zip(ins, outs):
                    scale = 100 if bypass else 50
                    self.assertEqual((i, q), (scale*n, -scale*n), f"beat {n}")
                    self.assertEqual(c_out - c_in, dut.latency, f"beat {n}")

if __name__ == "__main__":
    unittest.main()
