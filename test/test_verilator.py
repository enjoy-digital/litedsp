#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Verilator (real HDL) co-simulation checks. Skipped when verilator is not installed."""

import unittest

from sim.verilator import have_verilator

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
