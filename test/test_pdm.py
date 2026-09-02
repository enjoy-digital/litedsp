#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from migen import *

from litedsp.audio.pdm import LiteDSPSigmaDeltaModulator, LiteDSPSigmaDeltaDAC, LiteDSPPDMReceiver

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import sigma_delta_model, pdm_receiver_model, bitstream_decimator_model

FS24 = (1 << 23) - 1

def fit_tone(y, cycles):
    """Least-squares fit of ``a*cos + b*sin`` at ``cycles`` periods over the record; returns
    (amplitude, residual power)."""
    y = np.asarray(y, float)
    n = len(y)
    t = np.arange(n)
    basis = np.stack([np.cos(2*np.pi*cycles*t/n), np.sin(2*np.pi*cycles*t/n)], axis=1)
    coef, *_ = np.linalg.lstsq(basis, y, rcond=None)
    resid = y - basis @ coef
    return float(np.hypot(*coef)), float(np.mean(resid**2))

class TestSigmaDeltaModulator(unittest.TestCase):
    # verify-tier: model — bit-exact bitstream under backpressure for both loop orders.
    def test_bit_exact(self):
        prng = random.Random(1)
        x = [prng.randint(-FS24//2, FS24//2) for _ in range(60)]
        for order in (1, 2):
            with self.subTest(order=order):
                dut = LiteDSPSigmaDeltaModulator(data_width=24, interpolation=8, order=order, with_csr=False)
                cap = run_stream(dut, [{"data": v} for v in x], 8*len(x), ["data"], ["data"],
                    sink_throttle=0.2, source_ready_rate=0.7)
                self.assertEqual(column(cap, "data").tolist(), sigma_delta_model(x, 8, order).tolist())
                self.assertEqual(dut.latency, 1)

    # verify-tier: bound — the bit density of a DC input tracks (1 + x)/2 within 0.5 %; a
    # -6 dBFS tone reconstructed through the sinc^4 model decimator (OSR 64) keeps >= 50 dB SNR
    # (second-order theory ~ 70 dB before CIC leakage; measured 58 dB), and the second-order
    # loop's residual is >= 10 dB below the first-order one (measured 24 dB).
    def test_density_and_snr(self):
        dut  = LiteDSPSigmaDeltaModulator(data_width=24, interpolation=64, order=2, with_csr=False)
        x    = [int(0.3*(1 << 23))]*16
        cap  = run_stream(dut, [{"data": v} for v in x], 64*len(x), ["data"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertAlmostEqual(np.mean(column(cap, "data")), 0.65, delta=0.005)
        n, cyc = 128, 5
        tone = [int(0.5*(1 << 23)*math.sin(2*math.pi*cyc*k/n)) for k in range(n)]
        dut  = LiteDSPSigmaDeltaModulator(data_width=24, interpolation=64, order=2, with_csr=False)
        cap  = run_stream(dut, [{"data": v} for v in tone], 64*n, ["data"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        bits = column(cap, "data")
        y    = bitstream_decimator_model(bits, 64, 4, 1, 24)[8:]              # Skip the CIC fill.
        amp, res = fit_tone(y, cyc*len(y)/n)
        snr2 = 10*math.log10(amp**2/2/res)
        self.assertGreaterEqual(snr2, 50.0)
        y1 = bitstream_decimator_model(sigma_delta_model(tone, 64, 1), 64, 4, 1, 24)[8:]
        amp1, res1 = fit_tone(y1, cyc*len(y1)/n)
        self.assertGreaterEqual(10*math.log10(res1/res), 10.0)

    def test_invalid(self):
        for kwargs in ({"order": 3}, {"interpolation": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPSigmaDeltaModulator(with_csr=False, **kwargs)

class TestSigmaDeltaDAC(unittest.TestCase):
    # verify-tier: model — the bits sampled on the pdm_clk rising edges contain each channel's
    # modulator model bitstream; the clock period is clk_div cycles; input starvation flags underrun.
    def test_bits_on_pins(self):
        prng   = random.Random(2)
        frames = 24
        xs     = [[prng.randint(-FS24//2, FS24//2) for _ in range(frames)] for _ in range(2)]
        beats  = [{"data": xs[c][k], "channel": c} for k in range(frames) for c in range(2)]
        dut    = LiteDSPSigmaDeltaDAC(data_width=24, n_channels=2, interpolation=4, order=2, clk_div=4,
            with_csr=False)
        bits, periods, seen = [[], []], [], {}
        @passive
        def sampler():
            prev, last, cyc = 0, None, 0
            while True:
                clk = (yield dut.pdm_clk)
                if clk and not prev:
                    for c in range(2):
                        bits[c].append((yield dut.pdm_out[c]))
                    if last is not None:
                        periods.append(cyc - last)
                    last = cyc
                prev = clk
                cyc += 1
                yield
        def driver():                                            # Inline push (stream_driver is passive).
            for b in beats:
                yield dut.sink.data.eq(b["data"])
                yield dut.sink.channel.eq(b["channel"])
                yield dut.sink.valid.eq(1)
                yield
                while (yield dut.sink.ready) == 0:
                    yield
            yield dut.sink.valid.eq(0)
            seen["underrun_early"] = (yield dut.underrun)
            for _ in range(frames*4*4 + 40):
                yield
            seen["underrun_late"] = (yield dut.underrun)
        run_simulation(dut, [driver(), sampler()])
        for c in range(2):
            ref = "".join(map(str, sigma_delta_model(xs[c], 4, 2)))
            self.assertIn(ref, "".join(map(str, bits[c])))
        self.assertEqual(set(periods), {4})
        self.assertEqual(seen["underrun_early"], 0)
        self.assertEqual(seen["underrun_late"], 1)

    def test_invalid(self):
        for kwargs in ({"clk_div": 3}, {"n_channels": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPSigmaDeltaDAC(with_csr=False, **kwargs)

class TestPDMReceiver(unittest.TestCase):
    def run_pins(self, dut, bits, n_out, ready_rate=1.0):
        """Launch per-channel bits on ``mdat`` like a microphone (channel 2*line after the mclk
        rising edge, channel 2*line + 1 after the falling edge when dual-edge) and capture the
        TDM source."""
        n_lines  = len(dut.mdat)
        dual     = dut.interface.dual_edge
        fields   = ["data", "channel"] if dut.n_channels > 1 else ["data"]
        captured = []
        @passive
        def mic():
            prev, idx = 0, [0]*len(bits)
            while True:
                clk = (yield dut.mclk)
                if clk != prev:
                    for line in range(n_lines):
                        c = 2*line + (0 if clk else 1) if dual else line
                        if (clk or dual) and idx[c] < len(bits[c]):
                            cur = (yield dut.mdat)
                            yield dut.mdat.eq((cur & ~(1 << line)) | (int(bits[c][idx[c]]) << line))
                            idx[c] += 1
                prev = clk
                yield
        run_simulation(dut, [mic(),
            stream_capture(dut.source, captured, n_out, fields, seed=3, ready_rate=ready_rate)])
        return column(captured, "data", 24), (column(captured, "channel") if dut.n_channels > 1
                                              else np.zeros(len(captured), np.int64))

    # verify-tier: model — short configuration (R=8, N=2, DC blocker, droop FIR) bit-exact against
    # the composed sub-models under output back-pressure.
    def test_bit_exact(self):
        prng = random.Random(4)
        n    = 64
        bits = [[prng.randint(0, 1) for _ in range(8*n)] for _ in range(2)]
        dut  = LiteDSPPDMReceiver(data_width=24, n_channels=2, decimation=8, n_stages=2, clk_div=4,
            dual_edge=True, with_dc_blocker=True, with_compensation=True, n_comp_taps=7, with_csr=False)
        data, ch = self.run_pins(dut, bits, 2*(n - 4), ready_rate=0.8)
        ref_d, ref_c = pdm_receiver_model(bits, 8, 2, 24, True, 10, dut.comp_coefficients)
        self.assertEqual(ch.tolist(), ref_c[:len(ch)].tolist())
        self.assertTrue(np.array_equal(data, ref_d[:len(data)]))
        self.assertIsNone(dut.latency)

    # verify-tier: bound — -6 dBFS tones (different frequencies per channel) modulated by the
    # sigma-delta model and received through OSR 64 sinc^4 + DC blocker read >= 45 dB SNR per
    # channel (a leak from the other channel would show as noise; OSR 32 measured 41.8 dB, the
    # second-order loop gains ~15 dB per OSR doubling).
    def test_tone_snr(self):
        n, R = 96, 64
        cycles = (4, 7)
        tones  = [[int(0.5*(1 << 23)*math.sin(2*math.pi*cycles[c]*k/n)) for k in range(n)] for c in range(2)]
        bits   = [sigma_delta_model(t, R, 2) for t in tones]
        dut    = LiteDSPPDMReceiver(data_width=24, n_channels=2, decimation=R, n_stages=4, clk_div=4,
            dual_edge=True, with_dc_blocker=True, with_csr=False)
        data, ch = self.run_pins(dut, bits, 2*(n - 4))
        for c in range(2):
            y = data[ch == c][12:]                                   # Skip the CIC / DC-blocker fill.
            amp, res = fit_tone(y, cycles[c]*len(y)/n)
            self.assertGreaterEqual(10*math.log10(amp**2/2/res), 45.0, f"channel {c}")

    # verify-tier: bound — CIC droop at 0.15 fs (sinc^4: -1.3 dB) is flattened by the 15-tap
    # compensation FIR to within 0.5 dB (measured 0.2 dB), from the amplitude ratio of two tones
    # (0.02 fs and 0.15 fs).
    def test_compensation_flattens_droop(self):
        n, R = 160, 32
        lo, hi = 3, 24
        tone = [int(0.2*(1 << 23)*(math.sin(2*math.pi*lo*k/n) + math.sin(2*math.pi*hi*k/n))) for k in range(n)]
        bits = [sigma_delta_model(tone, R, 2)]
        droop = {}
        for comp in (False, True):
            dut = LiteDSPPDMReceiver(data_width=24, n_channels=1, decimation=R, n_stages=4, clk_div=4,
                dual_edge=False, with_dc_blocker=False, with_compensation=comp, n_comp_taps=15, with_csr=False)
            data, _ = self.run_pins(dut, bits, n - 8)
            y = data[16:]
            a_lo, _ = fit_tone(y, lo*len(y)/n)
            a_hi, _ = fit_tone(y, hi*len(y)/n)
            droop[comp] = 20*math.log10(a_hi/a_lo)
        self.assertLess(droop[False], -1.0)
        self.assertLess(abs(droop[True]), 0.5)

    def test_invalid(self):
        for kwargs in ({"n_channels": 3, "dual_edge": True}, {"n_comp_taps": 8}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPDMReceiver(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
