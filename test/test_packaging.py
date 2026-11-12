#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Packaging: setup.py installs the litedsp package only (no stray top-level packages)."""

import os
import unittest
from unittest import mock

import setuptools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Helpers ------------------------------------------------------------------------------------------

def setup_kwargs():
    """Run setup.py with setuptools.setup mocked and return the arguments it was given."""
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        with mock.patch.object(setuptools, "setup") as setup:
            with open("setup.py", encoding="utf-8") as f:
                exec(compile(f.read(), "setup.py", "exec"), {"__name__": "__main__"})
    finally:
        os.chdir(cwd)
    return setup.call_args.kwargs

# Test Packaging -----------------------------------------------------------------------------------

class TestPackaging(unittest.TestCase):
    def test_only_litedsp_packages(self):
        packages = setup_kwargs()["packages"]
        self.assertIn("litedsp", packages)
        self.assertIn("litedsp.flow", packages)
        stray = sorted(p for p in packages if p != "litedsp" and not p.startswith("litedsp."))
        self.assertEqual(stray, [])

if __name__ == "__main__":
    unittest.main()
