#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Fast CI gate on the quality characterization suite (char/).

Re-measures a representative 5-metric subset (pure-NumPy specs only — the full sweep incl.
the CORDIC Migen simulation runs via ``python3 char/run_char.py``) and gates each value
against the checked-in guaranteed budgets in ``char/budgets.json``.
"""

import unittest

from char import budgets
from char.specs import SPECS

class TestChar(unittest.TestCase):
    _measured = {}                                  # Block spec results, cached across tests.

    def gate(self, block, metric):
        if block not in self._measured:
            self._measured[block] = SPECS[block]()
        value = self._measured[block][metric]
        entry = budgets.load()[block][metric]
        bound = budgets.bound(entry)
        if entry["direction"] == "min":
            self.assertGreaterEqual(value, bound,
                f"{block}.{metric} {value:.3f} < guaranteed {bound:.3f}")
        else:
            self.assertLessEqual(value, bound,
                f"{block}.{metric} {value:.3f} > guaranteed {bound:.3f}")

    # verify-tier: bound (guaranteed characterization values, see doc/characterization.md).
    def test_nco_sfdr(self):
        self.gate("nco", "sfdr_db")

    def test_fir_stopband_atten(self):
        self.gate("fir", "stopband_atten_db")

    def test_cic_droop_r8_n3(self):
        self.gate("cic", "droop_err_r8_n3_db")

    def test_mixer_image_rejection(self):
        self.gate("mixer", "image_rejection_db")

    def test_window_sidelobe(self):
        self.gate("window", "sidelobe_level_db")

if __name__ == "__main__":
    unittest.main()
