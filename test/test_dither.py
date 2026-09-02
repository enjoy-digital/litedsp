#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.audio.dither import LiteDSPDither

from test.common import run_stream, column
from test.models import dither_model

FS24 = (1 << 23) - 1

def band_power_db(x, f_lo, f_hi):
    spec = np.abs(np.fft.rfft(x*np.hanning(len(x))))**2
    f    = np.fft.rfftfreq(len(x))
    return 10*np.log10(np.sum(spec[(f >= f_lo) & (f < f_hi)]) + 1e-30)

class TestDither(unittest.TestCase):
    def run_dither(self, beats, throttle=0.2, ready_rate=0.7, extra=None, **kwargs):
        dut = LiteDSPDither(data_width=24, out_width=16, with_csr=False, **kwargs)
        fields = ["data", "channel"] if dut.n_channels > 1 else ["data"]
        cap = run_stream(dut, beats, len(beats), fields, fields, sink_throttle=throttle,
            source_ready_rate=ready_rate, extra=extra)
        return dut, column(cap, "data", 24)

    # verify-tier: model — generators advance per accepted beat, per-channel error state;
    # bit-exact for the three shaping structures with the shaping toggled mid-stream.
    def test_bit_exact(self):
        n    = 300
        prng = random.Random(1)
        beats = [{"data": prng.randint(-FS24, FS24), "channel": k % 2} for k in range(n)]
        for shaping in ("none", "ef1", "ef2"):
            with self.subTest(shaping=shaping):
                dut, got = self.run_dither(beats, shaping=shaping)
                ref = dither_model([b["data"] for b in beats], [b["channel"] for b in beats],
                    shaping=shaping)
                self.assertTrue(np.array_equal(got, ref))
                self.assertEqual(dut.latency, 1)
        dut = LiteDSPDither(data_width=24, out_width=16, shaping="ef2", with_csr=False)

        @passive
        def toggle():
            accepted = 0
            while accepted < 150:
                yield
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    accepted += 1
            yield dut.shaping_enable.eq(0)
            while True:
                yield

        cap = run_stream(dut, beats, n, ["data", "channel"], ["data", "channel"],
            sink_throttle=0.2, source_ready_rate=0.7, extra=[toggle()])
        ref = dither_model([b["data"] for b in beats], [b["channel"] for b in beats],
            shaping="ef2", shaping_enable=np.array([1]*150 + [0]*(n - 150)))
        self.assertTrue(np.array_equal(column(cap, "data", 24), ref))

    # verify-tier: bound — a -84 dBFS tone (2 LSB of the 16-bit output) rounded 24 -> 16 bits
    # becomes a staircase whose harmonics (2..9, coherent bins) stand > 10 dB above the
    # surrounding noise bins; with TPDF dither the error is decorrelated from the signal and
    # the harmonic bins sink into the noise floor (excess < 3 dB). Measured at LITEDSP_SEED=0
    # in the assertion messages.
    def test_tpdf_removes_distortion(self):
        n, k_tone = 4096, 37
        x = np.round(FS24*10**(-84/20)*np.sin(2*np.pi*k_tone*np.arange(n)/n)).astype(np.int64)
        beats = [{"data": int(v)} for v in x]
        excess = {}
        for enable in (0, 1):
            dut = LiteDSPDither(data_width=24, out_width=16, n_channels=1, with_csr=False)
            dut.dither_enable.reset = enable
            cap = run_stream(dut, beats, n, ["data"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
            y    = column(cap, "data", 24).astype(float)
            spec = np.abs(np.fft.rfft(y))**2
            hbins = [h*k_tone for h in range(2, 10)]
            harm  = np.mean([spec[b] for b in hbins])
            noise = np.mean([spec[b + d] for b in hbins for d in (-3, -2, 2, 3)])
            excess[enable] = 10*np.log10(harm/noise)
        self.assertGreater(excess[0], 10.0, f"harmonic excess without dither {excess[0]:.1f} dB")
        self.assertLess(excess[1], 3.0, f"harmonic excess with dither {excess[1]:.1f} dB")

    # verify-tier: bound — second-order error feedback moves the requantization noise out of
    # the 0..0.1 fs band: the in-band error power drops by >= 6 dB vs plain dither (theory for
    # (1 - z^-1)^2 integrated over the band ~ -12 dB; measured in the assertion message).
    def test_ef2_lowers_inband_noise(self):
        n    = 4096
        prng = random.Random(2)
        x    = np.array([prng.randint(-FS24//4, FS24//4) for _ in range(n)])
        # A low-frequency program: random walk filtered to keep it in-band.
        x    = np.cumsum(x)//64
        x    = np.clip(x - x.mean(), -FS24//2, FS24//2).astype(np.int64)
        inband = {}
        for shaping in ("none", "ef2"):
            dut = LiteDSPDither(data_width=24, out_width=16, n_channels=1, shaping=shaping, with_csr=False)
            cap = run_stream(dut, [{"data": int(v)} for v in x], n, ["data"], ["data"],
                sink_throttle=0.0, source_ready_rate=1.0)
            err = column(cap, "data", 24).astype(float) - x
            inband[shaping] = band_power_db(err, 0.0, 0.1)
        self.assertGreater(inband["none"] - inband["ef2"], 6.0,
            f"in-band noise none {inband['none']:.1f} / ef2 {inband['ef2']:.1f} dB")

    def test_saturation_bypass_invalid(self):
        beats = [{"data": FS24, "channel": 0}, {"data": -FS24 - 1, "channel": 1}]*20
        dut, got = self.run_dither(beats)
        self.assertTrue(np.all(np.abs(got) <= (1 << 23)))
        self.assertEqual(int(got[0]), ((1 << 15) - 1) << 8)          # +FS clamps at the 16-bit max.
        dut = LiteDSPDither(data_width=24, out_width=16, with_csr=False)
        dut.bypass.reset = 1
        cap = run_stream(dut, beats, len(beats), ["data", "channel"], ["data", "channel"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data", 24), [b["data"] for b in beats]))
        for kwargs in ({"out_width": 24}, {"shaping": "ef3"}, {"seed": 0}, {"n_channels": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPDither(data_width=24, with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
