#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""The LiteX coding-style checker (``tools/check_style.py``) passes on the whole tree."""

import os
import sys
import unittest
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestStyle(unittest.TestCase):
    # verify-tier: policy — header, 100-column separators, '# # #' separator, import grouping,
    # CSR declaration style, script hygiene and the soft line length on every Python file.
    def test_coding_style(self):
        result = subprocess.run([sys.executable, os.path.join("tools", "check_style.py")],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
            "coding-style violations:\n" + result.stdout[-4000:] + result.stderr[-500:])

if __name__ == "__main__":
    unittest.main()
