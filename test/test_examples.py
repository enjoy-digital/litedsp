#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Elaborate the standalone core generator configs shipped in examples/*.yml."""

import os
import sys
import glob
import unittest
import tempfile
import subprocess

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

class TestAppNoteExamples(unittest.TestCase):
    """Headless CI smoke of the app-note example scripts: run end-to-end, exit 0.

    Plots go to a temp dir (committed PNGs untouched); MPLBACKEND=Agg keeps matplotlib
    headless, and the scripts skip plotting gracefully when matplotlib is absent.
    """
    def _run_example(self, name, timeout=560):
        env = dict(os.environ, MPLBACKEND="Agg")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, os.path.join(EXAMPLES_DIR, name), "--plot-dir", tmp],
                env=env, capture_output=True, text=True, timeout=timeout)
        self.assertEqual(result.returncode, 0,
            f"{name} exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
        self.assertIn("PASS", result.stdout, f"{name} did not report PASS:\n{result.stdout}")

    def test_fm_stereo_receiver_smoke(self):  # AN001.
        self._run_example("fm_stereo_receiver.py")

    def test_qpsk_modem_smoke(self):        # AN002.
        self._run_example("qpsk_modem.py")

    def test_spectrum_monitor_smoke(self):  # AN003.
        self._run_example("spectrum_monitor.py")

    def test_chirp_radar_smoke(self):       # AN004.
        self._run_example("chirp_radar.py")

if __name__ == "__main__":
    unittest.main()
