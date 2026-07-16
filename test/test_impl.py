#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Implementation smoke test: a couple of blocks synthesize clean for ECP5 (Yosys).

Full coverage + resource budgets live in impl/run.py and the Implementation CI workflow; this
just guards portability/compile-cleanliness in the normal test run. Skipped without Yosys.
"""

import os
import json
import tempfile
import unittest
from unittest import mock

from impl import budgets, ecp5, wrap, modules


class TestImplementationBudgets(unittest.TestCase):
    def test_update_preserves_measured_fmax_and_gate_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with mock.patch.object(budgets, "PATH", path):
                budgets.update("ecp5", {
                    "example": {
                        "lut": 10, "ff": 20, "bram": 1, "dsp": 2,
                        "pnr": {"fmax_mhz": 123.456},
                    },
                }, flow="pnr")
                with open(path) as f:
                    entry = json.load(f)["example"]["ecp5"]
        self.assertEqual(entry["fmax_mhz"], 123.5)
        self.assertEqual(entry["fmax_min"], 104.9)
        self.assertEqual(entry["pnr"]["fmax_mhz"], 123.5)

    def test_update_preserves_explicit_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with open(path, "w") as f:
                json.dump({"example": {"ecp5": {"fmax_target": 150.0}}}, f)
            with mock.patch.object(budgets, "PATH", path):
                budgets.update("ecp5", {"example": {"pnr": {"fmax_mhz": 123.456}}},
                    flow="pnr")
                entry = budgets.load()["example"]["ecp5"]
        self.assertEqual(entry["fmax_target"], 150.0)
        self.assertEqual(entry["fmax_min"], 104.9)

    def test_target_check_is_separate_from_regression_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with open(path, "w") as f:
                json.dump({"example": {"ecp5": {
                    "fmax_min": 80.0, "fmax_target": 100.0,
                }}}, f)
            result = {"pnr": {"fmax_mhz": 90.0}}
            with mock.patch.object(budgets, "PATH", path):
                self.assertEqual(budgets.check("ecp5", "example", result, flow="pnr"), [])
                self.assertEqual(budgets.check_target("ecp5", "example", result),
                    ["fmax 90.0 < target 100.0 MHz"])

    def test_synth_and_pnr_resource_baselines_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with mock.patch.object(budgets, "PATH", path):
                budgets.update("xilinx", {"fft": {"lut": 295, "ff": 90}}, flow="synth")
                budgets.update("xilinx", {"fft": {
                    "lut": 254, "ff": 90, "pnr": {"fmax_mhz": 104.5},
                }}, flow="pnr")
                entry = budgets.load()["fft"]["xilinx"]
                self.assertEqual(entry["synth"]["lut"], 295)
                self.assertEqual(entry["pnr"]["lut"], 254)
                self.assertEqual(entry["lut"], 254)  # Flat display view prefers P&R.
                self.assertEqual(budgets.check("xilinx", "fft", {"lut": 295},
                    flow="synth"), [])
                self.assertEqual(budgets.check("xilinx", "fft", {"lut": 254},
                    flow="pnr"), [])

    def test_migrate_seeds_timed_and_synthesis_only_entries(self):
        data = {
            "timed": {"ecp5": {"lut": 10, "ff": 2, "fmax_mhz": 100.0,
                "fmax_min": 85.0, "fmax_target": 100.0}},
            "synth": {"ecp5": {"lut": 5, "ff": 1}},
        }
        budgets.migrate(data)
        self.assertEqual(data["timed"]["ecp5"]["synth"]["lut"], 10)
        self.assertEqual(data["timed"]["ecp5"]["pnr"]["fmax_min"], 85.0)
        self.assertNotIn("pnr", data["synth"]["ecp5"])

    def test_closed_targets_are_pnr_sentinels(self):
        data = budgets.load()
        self.assertEqual(modules.TARGET_CLOSED,
            ["dpd", "ddc", "channelizer", "ldpc_decoder",
             "cic_decimator", "cic_interpolator", "agc", "fft_iter",
             "viterbi_decoder", "viterbi_decoder_soft",
             "cic_parallel_x2", "cic_parallel_x4",
             "fft_folded", "goertzel_folded", "iir_biquad_folded",
             "pfb_channelizer_folded", "timing_recovery", "cfr_pipelined"])
        for name in modules.TARGET_CLOSED:
            self.assertIn(name, modules.PNR_SUBSET)
            entry = data[name]["ecp5"]
            self.assertGreaterEqual(entry["pnr"]["fmax_mhz"], entry["fmax_target"])

@unittest.skipUnless(ecp5.have_yosys(), "yosys not installed")
class TestImplementationECP5(unittest.TestCase):
    def synth(self, name):
        dut, ios, _ = modules.REGISTRY[name]()
        bd = os.path.join("/tmp/litedsp_impl_test", name)
        verilog = wrap.gen(name, dut, ios, bd)
        return ecp5.synth(verilog, name, bd)

    def test_nco_synthesizes(self):
        res = self.synth("nco")
        self.assertGreater(res["lut"], 0)
        self.assertGreater(res["ff"], 0)

    def test_fir_synthesizes(self):
        res = self.synth("fir_complex")
        self.assertGreater(res["lut"], 0)
        self.assertGreater(res["dsp"], 0)      # FIR uses multipliers.

if __name__ == "__main__":
    unittest.main()
