#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Verilator (real HDL) co-simulation checks. Skipped when verilator is not installed."""

import unittest
from unittest import mock

from sim.verilator import build, have_verilator

class TestVerilatorCommand(unittest.TestCase):
    def test_build_waives_codegen_noise_but_keeps_structural_warnings(self):
        with mock.patch("sim.verilator.subprocess.check_call") as check_call:
            build("dut.v", "tb.cpp", "dut", "/tmp/litedsp_verilator_command")
        cmd = check_call.call_args.args[0]
        for flag in ("-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC", "-Wno-INITIALDLY",
                     "-Wno-COMBDLY"):
            self.assertIn(flag, cmd)
        self.assertNotIn("-Wno-WIDTH", cmd)
        for structural in ("-Wno-LATCH", "-Wno-UNOPTFLAT", "-Wno-MULTIDRIVEN"):
            self.assertNotIn(structural, cmd)

@unittest.skipUnless(have_verilator(), "verilator not installed")
class TestVerilator(unittest.TestCase):
    def test_nco(self):
        from sim.run_nco import main as run_nco
        self.assertTrue(run_nco(n=128))

    def test_fir(self):
        from sim.run_fir import main as run_fir
        self.assertTrue(run_fir(n=128))

if __name__ == "__main__":
    unittest.main()
