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
                })
                with open(path) as f:
                    entry = json.load(f)["example"]["ecp5"]
        self.assertEqual(entry["fmax_mhz"], 123.5)
        self.assertEqual(entry["fmax_min"], 104.9)

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
