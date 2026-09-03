#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.comm.hdlc   import LiteDSPHDLCFramer, LiteDSPHDLCDeframer
from litedsp.comm.design import hdlc_frame_bits, HDLC_FLAG

from test.common import run_stream, column
from test.models import hdlc_frame_model, hdlc_deframe_model

def payload_beats(payloads):
    beats = []
    for p in payloads:
        for k, b in enumerate(p):
            beats.append({"data": int(b), "first": int(k == 0), "last": int(k == len(p) - 1)})
    return beats

class TestHDLC(unittest.TestCase):
    # verify-tier: model — three payloads (48, 96 and 7 bits, one with a run of ones that gets
    # stuffed) through the framer (two preamble flags) bit-exact against the model with the flag
    # framing, then the deframer recovers them bit-exact (first / last / fcs_ok) and counts the
    # frames; the round trip under backpressure.
    def test_round_trip(self):
        prng = random.Random(9)
        payloads = [[prng.randint(0, 1) for _ in range(48)], [1]*12 + [0] + [1]*20 + [prng.randint(0, 1) for _ in range(63)], [1, 0, 1, 1, 1, 1, 1]]
        fr = LiteDSPHDLCFramer(preamble=2, with_csr=False)
        bits, first, last = hdlc_frame_model(payloads, 2)
        cap = run_stream(fr, payload_beats(payloads), len(bits), ["data", "first", "last"], ["data", "first", "last"], sink_throttle=0.2, source_ready_rate=0.7)
        self.assertEqual(column(cap, "data").tolist(), bits.tolist())
        self.assertEqual(column(cap, "first").tolist(), first.tolist())
        self.assertEqual(column(cap, "last").tolist(), last.tolist())
        line = bits.tolist() + [(HDLC_FLAG >> i) & 1 for i in range(8)]*2
        (data, f, l, ok), stats = hdlc_deframe_model(line)
        self.assertEqual(data.tolist(), sum(payloads, []))
        self.assertEqual(stats, dict(frames=3, fcs_errors=0, aborts=0))
        de = LiteDSPHDLCDeframer(with_csr=False)
        cap = run_stream(de, [{"data": b} for b in line], len(data), ["data"], ["data", "first", "last", "fcs_ok"], sink_throttle=0.2, source_ready_rate=0.7,
            extra=[self._status(de)])
        self.assertEqual(column(cap, "data").tolist(), data.tolist())
        self.assertEqual(column(cap, "first").tolist(), f.tolist())
        self.assertEqual(column(cap, "last").tolist(), l.tolist())
        self.assertEqual(column(cap, "fcs_ok").tolist(), ok.tolist())
        self.assertEqual((self.frames, self.fcs_errors, self.aborts, self.fcs_error), (3, 0, 0, 0))

    # verify-tier: bound — a corrupted payload bit delivers the payload with fcs_ok = 0 and the
    # sticky FCS error; an aborted frame (seven ones) is dropped and counted (a frame aborted after
    # more than 24 accepted bits would have leaked its withheld bits without last); idle flags
    # between frames are not frames; invalid preamble.
    def test_errors_and_abort(self):
        prng = random.Random(10)
        p1, p2 = [prng.randint(0, 1) for _ in range(40)], [prng.randint(0, 1) for _ in range(40)]
        good = hdlc_frame_bits(p1)
        bad = list(good); bad[8 + 5] ^= 1                              # A payload bit (flag is 8 bits).
        flag = [(HDLC_FLAG >> i) & 1 for i in range(8)]
        aborted = flag + p2[:15] + [1]*8 + flag                         # < 24 bits accepted: nothing leaks.
        line = bad + flag*3 + aborted + hdlc_frame_bits(p2) + flag*2
        (data, f, l, ok), stats = hdlc_deframe_model(line)
        self.assertEqual(stats, dict(frames=2, fcs_errors=1, aborts=1))
        self.assertEqual(len(data), 80)
        self.assertEqual(ok.tolist(), [0]*39 + [0] + [0]*39 + [1])
        de = LiteDSPHDLCDeframer(with_csr=False)
        cap = run_stream(de, [{"data": b} for b in line], 80, ["data"], ["data", "last", "fcs_ok"], sink_throttle=0.0, source_ready_rate=1.0,
            extra=[self._status(de)])
        self.assertEqual(column(cap, "data").tolist(), data.tolist())
        self.assertEqual(column(cap, "fcs_ok").tolist(), ok.tolist())
        self.assertEqual((self.frames, self.fcs_errors, self.aborts, self.fcs_error), (2, 1, 1, 1))
        with self.assertRaises(ValueError):
            LiteDSPHDLCFramer(preamble=0, with_csr=False)

    def _status(self, dut):
        def gen():
            for _ in range(2500):
                self.frames = (yield dut.frames)
                self.fcs_errors = (yield dut.fcs_errors)
                self.aborts = (yield dut.aborts)
                self.fcs_error = (yield dut.fcs_error)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
