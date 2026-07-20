#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import json
import tempfile
import unittest

from sim.run_coverage import load_waivers


class TestCoverageWaivers(unittest.TestCase):
    def test_semantic_checks_resolve(self):
        waivers = load_waivers()
        self.assertEqual(set(waivers), {"equalizer", "ldpc_decoder", "pfb_channelizer_fft"})
        self.assertGreaterEqual(len(waivers["ldpc_decoder"]["semantic_checks"]), 5)

    def test_unresolved_check_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({"bad": {"reason": "test", "semantic_checks": [
                "test.test_ldpc:TestLDPC.not_a_test"]}}, f)
            f.flush()
            with self.assertRaises(ValueError):
                load_waivers(f.name)


if __name__ == "__main__":
    unittest.main()
