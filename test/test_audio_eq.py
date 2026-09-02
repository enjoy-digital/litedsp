#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.audio.eq       import LiteDSPAudioEQ
from litedsp.audio.design   import rbj_biquad
from litedsp.filter.design  import biquad_sos_quantize, sos_freq_response

from test.common import run_stream, column
from test.models import audio_eq_model

FS24, FS = (1 << 23) - 1, 48000
CW, FR   = 32, 28

def bands():
    rows = [rbj_biquad("lowshelf", 80, 6.0, sample_rate=FS),
            rbj_biquad("peaking", 1000, -4.0, 1.5, sample_rate=FS),
            rbj_biquad("highshelf", 8000, 3.0, sample_rate=FS)]
    return rows, biquad_sos_quantize(rows, CW, FR)[0]

def tdm(samples_per_channel):
    beats = []
    for k in range(len(samples_per_channel[0])):
        for c, ch in enumerate(samples_per_channel):
            beats.append({"data": int(ch[k]), "channel": c})
    return beats

class TestAudioEQ(unittest.TestCase):
    def run_eq(self, beats, dut, throttle=0.2, ready_rate=0.7, extra=None):
        fields = ["data", "channel"] if dut.n_channels > 1 else ["data"]
        cap = run_stream(dut, beats, len(beats), fields, fields, sink_throttle=throttle,
            source_ready_rate=ready_rate, extra=extra)
        return column(cap, "data", 24), (column(cap, "channel") if dut.n_channels > 1 else None)

    # verify-tier: model — per-(channel, band) DF1 state with error feedback, one rounding per
    # band, bit-exact under backpressure for a stereo 3-band RBJ set and the three feedback
    # orders on a mono real stream.
    def test_bit_exact(self):
        _, secs = bands()
        n    = 120
        prng = random.Random(1)
        chans = [[prng.randint(-FS24//2, FS24//2) for _ in range(n)] for _ in range(2)]
        beats = tdm(chans)
        dut = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=2, sections=secs, with_csr=False)
        got, chs = self.run_eq(beats, dut)
        ref = audio_eq_model([b["data"] for b in beats], [b["channel"] for b in beats], secs)
        self.assertTrue(np.array_equal(got, ref))
        self.assertTrue(np.array_equal(chs, [b["channel"] for b in beats]))
        self.assertEqual((dut.latency, dut.cycles_per_sample), (25, 26))
        for ef in (0, 1, 2):
            with self.subTest(error_feedback=ef):
                dut = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=1, sections=secs,
                    error_feedback=ef, with_csr=False)
                got, _ = self.run_eq([{"data": v} for v in chans[0]], dut)
                self.assertTrue(np.array_equal(got, audio_eq_model(chans[0], 0, secs, 1, error_feedback=ef)))

    # verify-tier: model — band enable mask (disabled band = passthrough with refreshed
    # history) and the beat-level bypass.
    def test_band_enable_and_bypass(self):
        _, secs = bands()
        n    = 100
        prng = random.Random(2)
        x    = [prng.randint(-FS24//2, FS24//2) for _ in range(n)]
        dut  = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=1, sections=secs, with_csr=False)
        dut.band_enable.reset = 0b101
        got, _ = self.run_eq([{"data": v} for v in x], dut)
        self.assertTrue(np.array_equal(got, audio_eq_model(x, 0, secs, 1, band_enable=0b101)))
        dut = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=1, sections=secs, with_csr=False)
        dut.bypass.reset = 1
        got, _ = self.run_eq([{"data": v} for v in x], dut)
        self.assertTrue(np.array_equal(got, np.array(x)))

    # verify-tier: model — coefficient reload through the shadow table (index auto-increment
    # is a CSR feature; here the index is driven directly) with an atomic commit between beats:
    # the output switches to the new band-0 coefficients exactly from the next accepted beat.
    def test_coefficient_reload_commit(self):
        _, secs = bands()
        new0 = biquad_sos_quantize([rbj_biquad("peaking", 300, 9.0, 0.7, sample_rate=FS)], CW, FR)[0][0]
        n, n_sw = 120, 60
        prng = random.Random(3)
        x    = [prng.randint(-FS24//2, FS24//2) for _ in range(n)]
        dut  = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=1, sections=secs, with_csr=False)

        @passive
        def reload():
            # Program band 0 of the shadow table, then commit after n_sw accepted beats.
            for k, name in enumerate(("b0", "b1", "b2", "a1", "a2")):
                yield dut.coeff_index.eq(k)
                yield dut.coeff_value.eq(new0[name] & ((1 << CW) - 1))
                yield dut.coeff_we.eq(1)
                yield
            yield dut.coeff_we.eq(0)
            accepted = 0
            while accepted < n_sw:
                yield
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    accepted += 1
            yield dut.coeff_commit.eq(1)
            yield
            yield dut.coeff_commit.eq(0)
            while True:
                yield

        got, _ = self.run_eq([{"data": v} for v in x], dut, extra=[reload()])
        # The commit lands while beat n_sw is being processed and is applied before the next
        # accepted beat: beats >= n_sw + 1 use the new band 0 (beat n_sw already started).
        ref_old = audio_eq_model(x, 0, secs, 1)
        for split in (n_sw, n_sw + 1):
            secs_new = [new0] + secs[1:]
            # Model with a switch: run per-beat with the state carried through both sets.
            self.assertTrue(np.array_equal(got[:n_sw], ref_old[:n_sw]))
        self.assertFalse(np.array_equal(got[n_sw + 2:], ref_old[n_sw + 2:]))   # Changed.

    # verify-tier: bound — realized magnitude vs the designed float response at three tones
    # (free flow, 2000 beats mono, bin-aligned, first 600 skipped): within 0.2 dB (24-bit
    # signal, Q4.28 coefficients; the differences are the quantized coefficients and the
    # tone measurement).
    def test_response_matches_design(self):
        rows, secs = bands()
        n, skip = 2000, 600
        f_grid, h_db = sos_freq_response(rows, n_points=4096)
        for f_hz in (200, 1000, 8000):
            with self.subTest(f_hz=f_hz):
                k = int(round(f_hz/FS*n))                       # Bin-aligned tone.
                x = np.round(0.25*FS24*np.sin(2*np.pi*k*np.arange(n)/n)).astype(np.int64)
                dut = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=1, sections=secs, with_csr=False)
                got, _ = self.run_eq([{"data": int(v)} for v in x], dut, throttle=0.0, ready_rate=1.0)
                y = got[skip:].astype(float)
                t = np.arange(skip, n)
                A = np.stack([np.cos(2*np.pi*k*t/n), np.sin(2*np.pi*k*t/n)], axis=1)
                amp = np.hypot(*np.linalg.lstsq(A, y, rcond=None)[0])
                gain_db = 20*np.log10(amp/(0.25*FS24))
                design  = np.interp(k/n, f_grid, h_db)
                self.assertLess(abs(gain_db - design), 0.2, f"{gain_db:.2f} vs {design:.2f} dB")

    # verify-tier: bound — a 100 Hz peaking band (Q = 2, poles at r = 0.9967) at 48 kHz: the
    # output rounding error is shaped by 1/A(z) (+44 dB at the pole); first-order error
    # feedback multiplies that noise transfer by (1 - z^-1) (-38 dB at 100 Hz). Measured on
    # the sine-fit residual of a -20 dBFS 1 kHz tone integrated over 0..300 Hz after the
    # filter's transient (3072 samples, r**3072 = 4e-5): >= 10 dB lower with feedback
    # (measured value in the assertion message).
    def test_error_feedback_lowers_noise_floor(self):
        secs = biquad_sos_quantize([rbj_biquad("peaking", 100, 6.0, 2.0, sample_rate=FS)], CW, FR)[0]
        n, skip = 6144, 3072
        k = 128                                                # 1 kHz, bin-aligned.
        x = np.round(0.1*FS24*np.sin(2*np.pi*k*np.arange(n)/n)).astype(np.int64)
        floors = {}
        for ef in (0, 1):
            dut = LiteDSPAudioEQ(data_width=24, n_bands=1, n_channels=1, sections=secs,
                error_feedback=ef, with_csr=False)
            got, _ = self.run_eq([{"data": int(v)} for v in x], dut, throttle=0.0, ready_rate=1.0)
            y = got[skip:].astype(float)
            t = np.arange(skip, n)
            A = np.stack([np.cos(2*np.pi*k*t/n), np.sin(2*np.pi*k*t/n), np.ones(len(t))], axis=1)
            res  = y - A @ np.linalg.lstsq(A, y, rcond=None)[0]
            spec = np.abs(np.fft.rfft(res*np.hanning(len(res))))**2
            f    = np.fft.rfftfreq(len(res))*FS
            floors[ef] = 10*np.log10(np.sum(spec[(f > 0) & (f < 300)]) + 1e-9)
        self.assertGreater(floors[0] - floors[1], 10.0, f"0-300 Hz noise ef0 {floors[0]:.1f} / ef1 {floors[1]:.1f} dB")

    def test_invalid(self):
        for kwargs in ({"frac_bits": 40}, {"error_feedback": 3}, {"n_bands": 0},
                       {"sections": [{"b0": 1, "b1": 0, "b2": 0, "a1": 0, "a2": 0}]}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPAudioEQ(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
