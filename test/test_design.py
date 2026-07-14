#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

try:
    import scipy.signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from litedsp.filter.fir import LiteDSPFIRFilter

from litedsp.filter.design import (
    firwin_lowpass, firwin_bandpass,
    remez, remez_lowpass,
    kaiser_window, kaiserord, firwin_kaiser,
    butterworth_sos, chebyshev1_sos, chebyshev2_sos, biquad_sos_quantize,
    freq_response, report, sos_freq_response,
)

from test.common import run_stream, column

def response_db(taps, freqs, frac_bits=15):
    taps = np.asarray(taps, dtype=float)/(1 << frac_bits)
    m    = np.arange(len(taps))
    H    = np.array([np.sum(taps*np.exp(-2j*np.pi*f*m)) for f in np.atleast_1d(freqs)])
    return 20*np.log10(np.maximum(np.abs(H), 1e-12))

def amplitude(taps, freqs):
    """Zero-phase amplitude A(f) of a linear-phase (symmetric) FIR (signed, not |H|)."""
    taps  = np.asarray(taps, dtype=float)
    freqs = np.atleast_1d(np.asarray(freqs, dtype=float))
    H     = np.exp(-2j*np.pi*np.outer(freqs, np.arange(len(taps)))) @ taps
    return (H*np.exp(1j*np.pi*freqs*(len(taps) - 1))).real

def count_alternations(taps, bands, desired, weights=None, level=0.9):
    """Count sign-alternating error extrema at >= ``level`` of the peak weighted error."""
    bands   = np.asarray(bands, dtype=float).reshape(-1, 2)
    weights = np.ones(len(bands)) if weights is None else np.asarray(weights, dtype=float)
    errors  = []
    for (f0, f1), d, w in zip(bands, desired, weights):
        f = np.linspace(f0, f1, 2048)
        errors.append(w*(amplitude(taps, f) - d))
    emax  = max(np.max(np.abs(e)) for e in errors)
    signs = []
    for e in errors:
        idx = ([0] + [i for i in range(1, len(e) - 1) if (e[i] - e[i-1])*(e[i+1] - e[i]) <= 0]
                   + [len(e) - 1])
        for i in idx:
            if abs(e[i]) < level*emax:
                continue
            s = 1 if e[i] > 0 else -1
            if not signs or signs[-1] != s:
                signs.append(s)
    return len(signs)

class TestFIRDesign(unittest.TestCase):
    def test_bandpass_passband_and_rejection(self):
        f_low, f_high = 0.10, 0.20
        taps = firwin_bandpass(101, f_low, f_high)
        fc   = 0.5*(f_low + f_high)
        self.assertLess(abs(response_db(taps, fc)[0]),  1.0)   # ~0 dB at center.
        self.assertLess(response_db(taps, 0.0)[0],   -30)      # DC rejected.
        self.assertLess(response_db(taps, 0.40)[0],  -30)      # upper band rejected.

    def test_lowpass_still_unity_dc(self):
        taps = firwin_lowpass(63, 0.2)
        self.assertLess(abs(response_db(taps, 0.0)[0]), 0.5)   # ~0 dB at DC.
        self.assertLess(response_db(taps, 0.45)[0], -20)       # stopband.

class TestRemez(unittest.TestCase):
    def test_alternation_count(self):
        # Chebyshev alternation: an optimal length-63 design has >= 63//2 + 2 = 33 extrema.
        n_taps = 63
        bands, desired = [0, 0.2, 0.25, 0.5], [1.0, 0.0]
        taps = remez(n_taps, bands, desired)
        self.assertGreaterEqual(count_alternations(taps, bands, desired), n_taps//2 + 2)

    def test_meets_spec_at_band_edges(self):
        f_pass, f_stop = 0.2, 0.25
        taps  = remez_lowpass(63, f_pass, f_stop)
        delta = 10**(-report(taps, f_pass, f_stop)["stopband_atten_db"]/20)
        # Equal weights: the deviation at both band edges is bounded by the ripple delta.
        self.assertLessEqual(abs(amplitude(taps, f_pass)[0] - 1), 1.05*delta)
        self.assertLessEqual(abs(amplitude(taps, f_stop)[0]),     1.05*delta)

    def test_beats_firwin_lowpass(self):
        # The point of equiripple design: for equal taps, remez trades unneeded far-out
        # attenuation for a much better worst-case stopband than the windowed design.
        f_pass, f_stop = 0.2, 0.25
        rem = remez_lowpass(63, f_pass, f_stop, data_width=16)
        win = firwin_lowpass(63, 0.5*(f_pass + f_stop), data_width=16)
        atten_rem = report(rem, f_pass, f_stop, data_width=16)["stopband_atten_db"]
        atten_win = report(win, f_pass, f_stop, data_width=16)["stopband_atten_db"]
        self.assertGreater(atten_rem, atten_win + 6)

class TestKaiser(unittest.TestCase):
    def test_window_matches_numpy(self):
        for n, beta in [(15, 0.0), (32, 4.0), (63, 8.6)]:
            self.assertLess(np.max(np.abs(kaiser_window(n, beta) - np.kaiser(n, beta))), 1e-9)

    def test_kaiserord_estimate(self):
        # The estimator's predicted attenuation is within 20% of the realized one.
        ripple_db, tw = 60.0, 0.05
        taps     = firwin_kaiser(0.25, ripple_db, tw)
        achieved = report(taps, 0.25 - tw/2, 0.25 + tw/2)["stopband_atten_db"]
        self.assertLess(abs(achieved - ripple_db)/ripple_db, 0.2)

class TestIIRPrototypes(unittest.TestCase):
    def measure(self, sos, frac_bits=None):
        return sos_freq_response(sos, frac_bits=frac_bits, n_points=2048)

    def test_butterworth_lowpass(self):
        f_cutoff = 0.2
        sos      = butterworth_sos(4, f_cutoff)
        f, h_db  = self.measure(sos)
        self.assertAlmostEqual(h_db[np.argmin(np.abs(f - f_cutoff))], -3.01, delta=0.1)
        self.assertTrue(np.all(np.diff(h_db[f <= f_cutoff]) <= 1e-9))  # Monotonic passband.
        # Quantized (Q?.14 by default): relaxed margin.
        secs, frac = biquad_sos_quantize(sos)
        f, h_db = self.measure(secs, frac_bits=frac)
        self.assertAlmostEqual(h_db[np.argmin(np.abs(f - f_cutoff))], -3.01, delta=0.3)

    def test_butterworth_highpass(self):
        sos     = butterworth_sos(5, 0.15, btype="highpass")
        f, h_db = self.measure(sos)
        self.assertLess(h_db[0], -60)                       # DC rejected.
        self.assertAlmostEqual(h_db[-1], 0.0, delta=0.01)   # ~0 dB at Nyquist.
        self.assertAlmostEqual(h_db[np.argmin(np.abs(f - 0.15))], -3.01, delta=0.1)

    def test_chebyshev1(self):
        ripple_db, f_cutoff = 1.0, 0.2
        sos     = chebyshev1_sos(5, ripple_db, f_cutoff)
        f, h_db = self.measure(sos)
        passband = h_db[f <= f_cutoff]
        self.assertAlmostEqual(passband.max() - passband.min(), ripple_db, delta=0.1*ripple_db)
        self.assertAlmostEqual(passband.max(), 0.0, delta=0.05)  # Ripples up to unity.
        secs, frac = biquad_sos_quantize(sos)
        f, h_db  = self.measure(secs, frac_bits=frac)
        passband = h_db[f <= f_cutoff]
        self.assertAlmostEqual(passband.max() - passband.min(), ripple_db, delta=0.3*ripple_db)

    def test_chebyshev2(self):
        atten_db, f_stop = 40.0, 0.25
        sos     = chebyshev2_sos(4, atten_db, f_stop)
        f, h_db = self.measure(sos)
        self.assertAlmostEqual(h_db[f >= f_stop].max(), -atten_db, delta=2.0)
        self.assertAlmostEqual(h_db[0], 0.0, delta=0.01)  # Unity DC gain.
        secs, frac = biquad_sos_quantize(sos)
        f, h_db = self.measure(secs, frac_bits=frac)
        self.assertAlmostEqual(h_db[f >= f_stop].max(), -atten_db, delta=4.0)

class TestReport(unittest.TestCase):
    def test_report_on_known_design(self):
        f_pass, f_stop = 0.2, 0.25
        taps = remez_lowpass(63, f_pass, f_stop, data_width=16)
        rep  = report(taps, f_pass, f_stop, data_width=16)
        self.assertAlmostEqual(rep["dc_gain_db"], 0.0, delta=0.1)
        self.assertLess(rep["passband_ripple_db"], 0.2)
        self.assertGreater(rep["stopband_atten_db"], 50)
        # Ripple/attenuation are consistent: equal-weight equiripple deltas match closely.
        delta_pass = (10**(rep["passband_ripple_db"]/20) - 1)/2
        delta_stop = 10**(-rep["stopband_atten_db"]/20)
        self.assertLess(abs(delta_pass - delta_stop)/delta_stop, 0.25)

@unittest.skipUnless(HAS_SCIPY, "SciPy not available")
class TestSciPyCrossCheck(unittest.TestCase):
    def test_remez_matches_scipy(self):
        for n_taps in [63, 64]:
            mine   = remez(n_taps, [0, 0.2, 0.25, 0.5], [1, 0])
            theirs = scipy.signal.remez(n_taps, [0, 0.2, 0.25, 0.5], [1, 0], fs=1)
            self.assertLess(np.max(np.abs(mine - theirs)), 1e-3)
        mine   = remez(75, [0, 0.08, 0.12, 0.22, 0.26, 0.5], [0, 1, 0], weights=[10, 1, 10])
        theirs = scipy.signal.remez(75, [0, 0.08, 0.12, 0.22, 0.26, 0.5], [0, 1, 0],
            weight=[10, 1, 10], fs=1)
        self.assertLess(np.max(np.abs(mine - theirs)), 1e-3)

    def assert_sos_matches(self, mine, theirs, tol_db=0.1):
        f, h_db = sos_freq_response(mine, n_points=2048)
        _, H    = scipy.signal.sosfreqz(theirs, worN=f, fs=1)
        hs_db   = 20*np.log10(np.maximum(np.abs(H), 1e-12))
        mask    = (h_db > -80) & (hs_db > -80)  # dB compare is meaningless inside deep nulls.
        self.assertLess(np.max(np.abs(h_db[mask] - hs_db[mask])), tol_db)

    def test_iir_matches_scipy(self):
        # scipy Wn is normalized to Nyquist (2x our normalized frequency).
        self.assert_sos_matches(butterworth_sos(4, 0.2),
            scipy.signal.butter(4, 0.4, output="sos"))
        self.assert_sos_matches(butterworth_sos(5, 0.15, btype="highpass"),
            scipy.signal.butter(5, 0.3, btype="highpass", output="sos"))
        self.assert_sos_matches(chebyshev1_sos(5, 1.0, 0.2),
            scipy.signal.cheby1(5, 1.0, 0.4, output="sos"))
        self.assert_sos_matches(chebyshev2_sos(4, 40.0, 0.25),
            scipy.signal.cheby2(4, 40.0, 0.5, output="sos"))

class TestRemezGateware(unittest.TestCase):
    def test_remez_stopband_in_simulation(self):
        # End-to-end: the quantized remez design, run through the actual FIR gateware, meets
        # report()'s worst-case stopband number within 3 dB at the worst stopband frequency.
        n_taps, f_pass, f_stop = 63, 0.15, 0.22
        data_width = 16
        taps = remez_lowpass(n_taps, f_pass, f_stop, data_width=data_width)
        rep  = report(taps, f_pass, f_stop, data_width=data_width)
        # Worst-case stopband frequency (same grid as report()).
        freqs, h_db = freq_response(taps, n_points=4096, data_width=data_width)
        stopband    = freqs >= f_stop
        f_worst     = freqs[stopband][np.argmax(h_db[stopband])]
        # Drive a full-scale tone at f_worst through the gateware.
        n, amp = 2048, 30000
        x   = np.round(amp*np.cos(2*np.pi*f_worst*np.arange(n))).astype(int)
        dut = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width)
        for t in range(n_taps):
            dut.coeffs[t].reset = taps[t]  # Signed; do not mask (would corrupt negatives).
        captured = run_stream(dut, [{"data": int(v)} for v in x], n, ["data"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = column(captured, "data", data_width)[2*n_taps:].astype(float)
        y = y - y.mean()  # Remove output rounding bias before the RMS measurement.
        # Use the *actual* input RMS (a tone at Nyquist has RMS = amp, not amp/sqrt(2)).
        rms_in   = np.sqrt(np.mean((x - x.mean())**2))
        measured = 20*np.log10(rms_in/np.sqrt(np.mean(y**2)))
        self.assertLess(abs(measured - rep["stopband_atten_db"]), 3.0,
            f"simulated stopband {measured:.1f} dB vs reported {rep['stopband_atten_db']:.1f} dB")

if __name__ == "__main__":
    unittest.main()
