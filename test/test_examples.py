#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Elaborate the standalone core generator configs shipped in examples/*.yml."""

import os
import glob
import unittest
import tempfile

from litedsp.gen import generate_core

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "examples")

class TestExamples(unittest.TestCase):
    def test_yml_configs_generate(self):
        configs = sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.yml")))
        self.assertTrue(configs, "no examples/*.yml configs found")
        for path in configs:
            with self.subTest(config=os.path.basename(path)):
                with tempfile.TemporaryDirectory() as tmp:
                    verilog_path, ip = generate_core(path, output_dir=tmp)
                    self.assertTrue(os.path.exists(verilog_path))
                    self.assertTrue(os.path.exists(os.path.join(os.path.dirname(verilog_path), "csr.csv")))

if __name__ == "__main__":
    unittest.main()
