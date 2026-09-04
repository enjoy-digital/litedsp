#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import *

from litedsp.radar.detect import LiteDSPTargetList

from test.common import run_stream, column
from test.models import target_list_model

FIELDS = ["range", "doppler", "data", "hit", "first", "last"]

def bursts(counts, prng):
    beats = []
    for n in counts:
        for i in range(n):
            beats.append({"range": prng.randint(0, 1023), "doppler": prng.randint(0, 255),
                          "data": prng.randint(0, 2**17 - 1),
                          "hit": 1, "first": int(i == 0), "last": 0})
        beats.append(
            {"range": 0, "doppler": 0, "data": n, "hit": 0, "first": int(n == 0), "last": 1})
    return beats

class TestTargetList(unittest.TestCase):
    # verify-tier: model — four CPIs (3, 6, 0 and 2 records) through a 4-entry list: the kept
    # records and terminators are bit-exact under backpressure, the overflow flag and the dropped
    # count reflect the 6-record CPI, and the host readback returns the last sealed list.
    def test_bit_exact_overflow_readback(self):
        prng  = random.Random(7)
        beats = bursts([3, 6, 0, 2], prng)
        ref, dropped = target_list_model(
            *[[b[f] for b in beats] for f in ("range", "doppler", "data", "hit")], max_targets=4)
        dut = LiteDSPTargetList(max_targets=4, with_csr=False)
        self.readback = None
        cap = run_stream(dut, beats, len(ref[0]), FIELDS, FIELDS, sink_throttle=0.2,
                         source_ready_rate=0.5,
            extra=[self._monitor(dut, beats)])
        for name, col in zip(FIELDS, ref):
            self.assertEqual(column(cap, name).tolist(), col.tolist(), name)
        self.assertEqual(self.dropped, dropped)
        self.assertEqual(self.overflow, 1)
        self.assertEqual(self.cpi_count, 4)
        self.assertIsNone(dut.latency)
        expect = [(b["range"], b["doppler"], b["data"]) for b in beats[-3:-1]]
        self.assertEqual(self.readback, expect)
        with self.assertRaises(ValueError):
            LiteDSPTargetList(max_targets=1, with_csr=False)

    def _monitor(self, dut, beats):
        @passive
        def gen():
            done = False
            while True:
                self.dropped   = (yield dut.dropped)
                self.overflow  = (yield dut.overflow)
                self.cpi_count = (yield dut.cpi_count)
                if self.cpi_count == 4 and not done:
                    done = True
                    count = (yield dut.rd_count)
                    recs  = []
                    for i in range(count):
                        yield dut.rd_index.eq(i)
                        yield
                        yield
                        recs.append(
                            ((yield dut.rd_range), (yield dut.rd_doppler), (yield dut.rd_data)))
                    self.readback = recs
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
