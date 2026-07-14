#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the GUI's badge/response logic (litedsp.gui.badges / litedsp.gui.response).

Both modules are display-less (no DearPyGui import), so everything here runs headless.
"""

import os
import unittest

import numpy as np

from litedsp.flow import netlist as nlmod
from litedsp.flow import registry
from litedsp.filter import design

from litedsp.gui import badges
from litedsp.gui.response import response_for


def _ddc():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return nlmod.load(os.path.join(here, "litedsp", "flow", "examples", "ddc.json"))


class TestBadgeText(unittest.TestCase):
    def test_budgeted_key(self):
        b    = badges.budget_for("cic_decimator")           # Characterized in impl/budgets.json.
        self.assertIsNotNone(b)
        text = badges.badge_text("cic_decimator")
        self.assertIn(f"LUT {b['lut']:g}", text)
        self.assertIn(f"DSP {b['dsp']:g}", text)
        self.assertIn(f"{b['fmax_min']:g} MHz", text)
        self.assertIn(f"lat {registry.get('cic_decimator').latency:g}", text)

    def test_unbudgeted_key_degrades(self):
        self.assertIsNone(badges.budget_for("delay"))
        text = badges.badge_text("delay")
        self.assertIn("LUT —", text)
        self.assertIn("DSP —", text)

    def test_alias_maps_fir_real_to_fir_budget(self):
        self.assertEqual(badges.budget_for("fir_real"), badges.budgets()["fir"]["ecp5"])


class TestChainTotals(unittest.TestCase):
    def test_ddc_example(self):
        nl  = _ddc()
        reg = registry.registry()
        totals = badges.chain_totals(nl, reg)

        budgeted = [b for b in nl.blocks if badges.budget_for(b.type) is not None]
        self.assertEqual(totals["blocks"],   len(nl.blocks))
        self.assertEqual(totals["budgeted"], len(budgeted))
        for m in ("lut", "ff", "dsp", "bram"):
            self.assertEqual(totals[m], sum(badges.budget_for(b.type).get(m, 0) for b in budgeted))
        self.assertEqual(totals["fmax_min"],
            min(badges.budget_for(b.type)["fmax_min"] for b in budgeted
                if "fmax_min" in badges.budget_for(b.type)))

        # ddc.json is a single path lo -> mix -> lpf -> deci: the longest path is the whole chain.
        expected = sum(l for l in (reg[b.type].latency for b in nl.blocks) if isinstance(l, int))
        self.assertEqual(totals["latency"], expected)

        self.assertIn("blocks budgeted", badges.totals_text(totals))


class TestResponse(unittest.TestCase):
    def test_fir_lowpass_stopband(self):
        # Quantized 63-tap lowpass at cutoff 0.125: past the transition band the (fixed-point)
        # stopband must still be > 40 dB down.
        taps = design.firwin_lowpass(63, 0.125)
        freqs, h_db = response_for("fir_real", {"n_taps": 63, "coefficients": taps})
        self.assertAlmostEqual(h_db[0], 0.0, delta=0.1)          # Unity DC gain.
        stop = freqs >= 0.2                                      # Stop edge ~0.125 + 3.3/63.
        self.assertLess(h_db[stop].max(), -40)

    def test_cic_decimator_matches_closed_form(self):
        R, N = 8, 3
        freqs, h_db = response_for("cic_decimator", {"decimation": R, "n_stages": N})
        with np.errstate(divide="ignore", invalid="ignore"):
            expected = np.abs(np.sin(np.pi*freqs*R)/(R*np.sin(np.pi*freqs)))**N
        expected[0] = 1.0
        np.testing.assert_allclose(10**(h_db/20), np.maximum(expected, 1e-8), rtol=1e-6)

    def test_moving_average_null(self):
        # n_points=513 puts f = 1/L = 32/1024 exactly on the grid.
        freqs, h_db = response_for("moving_average", {"length_log2": 4}, n_points=513)
        self.assertLess(h_db[np.argmin(np.abs(freqs - 1/16))], -100)   # Null at f = 1/L.

    def test_dc_blocker_is_highpass(self):
        freqs, h_db = response_for("dc_blocker", {})
        self.assertLess(h_db[0], -100)                           # DC rejected.
        self.assertAlmostEqual(h_db[-1], 0.0, delta=0.2)         # ~unity at Nyquist.

    def test_notch_default_at_quarter_rate(self):
        # cos_w0 reset 0 -> f0 = 0.25; n_points=513 puts 0.25 exactly on the grid.
        freqs, h_db = response_for("notch", {}, n_points=513)
        self.assertLess(h_db[np.argmin(np.abs(freqs - 0.25))], -60)
        self.assertAlmostEqual(h_db[0], 0.0, delta=0.1)

    def test_allpass_is_flat(self):
        freqs, h_db = response_for("allpass", {})
        self.assertLess(np.abs(h_db).max(), 0.01)

    def test_non_filter_blocks_return_none(self):
        for key in ("capture", "mixer", "nco", "fft"):
            self.assertIsNone(response_for(key, {}))


if __name__ == "__main__":
    unittest.main()
