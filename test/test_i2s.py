#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.audio.i2s import LiteDSPI2SReceiver, LiteDSPI2STransmitter

from test.common import stream_capture, column
from test.models import i2s_frame_model, i2s_params

CONFIGS = [("i2s", 16, 16, 2), ("i2s", 24, 32, 2), ("left_justified", 24, 32, 2),
           ("right_justified", 16, 32, 2), ("tdm", 24, 32, 4), ("tdm", 16, 16, 8)]

def frames_for(prng, n_frames, n_channels, sample_width):
    lim = (1 << (sample_width - 1)) - 1
    return [[prng.randint(-lim, lim) for _ in range(n_channels)] for _ in range(n_frames)]

def beats_for(frames, sample_width, data_width=24):
    return [{"data": w << (data_width - sample_width), "channel": c}
            for frame in frames for c, w in enumerate(frame)]

def push(sink, beats):
    """Inline stream push (test.common.stream_driver is passive)."""
    for b in beats:
        yield sink.data.eq(b["data"])
        yield sink.channel.eq(b["channel"])
        yield sink.valid.eq(1)
        yield
        while (yield sink.ready) == 0:
            yield
    yield sink.valid.eq(0)

def pairs(sdata, lrck):
    return "".join(f"{s}{l}" for s, l in zip(sdata, lrck))

class TestI2STransmitter(unittest.TestCase):
    # verify-tier: model — the (sdata, lrck) levels sampled on the BCLK rising edges contain the
    # frame model for every format / width, MSB first with the format's alignment.
    def test_bitstream_matches_model(self):
        prng = random.Random(1)
        for fmt, sw, slot, n in CONFIGS:
            with self.subTest(fmt=fmt, sample_width=sw, slot_width=slot, n_channels=n):
                frames = frames_for(prng, 5, n, sw)
                dut = LiteDSPI2STransmitter(data_width=24, sample_width=sw, slot_width=slot,
                    n_channels=n, fmt=fmt, mode="master", bclk_div=4, with_csr=False)
                got_s, got_l = [], []
                @passive
                def sampler():
                    prev = 0
                    while True:
                        clk = (yield dut.bclk)
                        if clk and not prev:
                            got_s.append((yield dut.sdata))
                            got_l.append((yield dut.lrck))
                        prev = clk
                        yield
                def driver():
                    yield from push(dut.sink, beats_for(frames, sw))
                    for _ in range(3*n*slot*4):
                        yield
                run_simulation(dut, [driver(), sampler()])
                ref_s, ref_l = i2s_frame_model(frames, fmt, sw, slot, n)
                self.assertIn(pairs(ref_s, ref_l), pairs(got_s, got_l))
                self.assertIsNone(dut.latency)

    # verify-tier: bound — master clocks: BCLK period = bclk_div cycles, LRCK period = one frame.
    def test_master_clocks(self):
        dut = LiteDSPI2STransmitter(data_width=24, sample_width=24, slot_width=32, n_channels=2,
            fmt="i2s", mode="master", bclk_div=8, with_csr=False)
        edges = {"bclk": [], "lrck": []}
        def probe():
            prev = {"bclk": 0, "lrck": 0}
            for cyc in range(2000):
                for name in edges:
                    v = (yield getattr(dut, name))
                    if v and not prev[name]:
                        edges[name].append(cyc)
                    prev[name] = v
                yield
        run_simulation(dut, probe())
        self.assertEqual(set(np.diff(edges["bclk"])), {8})
        self.assertEqual(set(np.diff(edges["lrck"])), {2*32*8})

    def test_underrun(self):
        dut = LiteDSPI2STransmitter(data_width=24, n_channels=2, fmt="i2s", mode="master", bclk_div=4,
            with_csr=False)
        seen = {}
        def driver():
            for _ in range(400):
                yield
            seen["idle"] = (yield dut.underrun)
            yield from push(dut.sink, beats_for(frames_for(random.Random(2), 1, 2, 24), 24))
            for _ in range(3*2*32*4):
                yield
            seen["starved"] = (yield dut.underrun)
            yield dut.clear.eq(1)
            yield
            yield dut.clear.eq(0)
            yield
            seen["cleared"] = (yield dut.underrun)
        run_simulation(dut, driver())
        self.assertEqual((seen["idle"], seen["starved"], seen["cleared"]), (0, 1, 0))

class TestI2SReceiver(unittest.TestCase):
    def drive_lines(self, dut, sdata, lrck, half=3, idle=1):
        """Slave-mode line driver: BCLK toggles every ``half`` cycles, sdata/lrck change right
        after the falling edge; ``idle`` leading BCLK periods at the opposite LRCK level."""
        pol = i2s_params(dut.fmt, dut.sample_width, dut.slot_width)[1]
        lead = int(not pol) if pol is not None else 0
        seq = [(0, lead)]*idle*dut.slot_width + list(zip(sdata, lrck)) + [(0, lead)]*2*dut.slot_width
        for s, l in seq:
            yield dut.bclk.eq(0)
            yield dut.sdata.eq(s)
            yield dut.lrck.eq(l)
            for _ in range(half):
                yield
            yield dut.bclk.eq(1)
            for _ in range(half):
                yield

    # verify-tier: model — a slave receiver decodes the frame-model bitstream (6 sys cycles per
    # BCLK) into MSB-aligned, slot-tagged words for every format / width.
    def test_slave_decodes_model_bitstream(self):
        prng = random.Random(3)
        for fmt, sw, slot, n in CONFIGS:
            with self.subTest(fmt=fmt, sample_width=sw, slot_width=slot, n_channels=n):
                frames = frames_for(prng, 4, n, sw)
                dut = LiteDSPI2SReceiver(data_width=24, sample_width=sw, slot_width=slot,
                    n_channels=n, fmt=fmt, mode="slave", with_csr=False)
                captured = []
                sdata, lrck = i2s_frame_model(frames, fmt, sw, slot, n)
                run_simulation(dut, [self.drive_lines(dut, sdata, lrck),
                    stream_capture(dut.source, captured, 4*n, ["data", "channel"], seed=1, ready_rate=0.7)])
                exp = beats_for(frames, sw)
                self.assertEqual(column(captured, "data", 24).tolist(), [b["data"] for b in exp])
                self.assertEqual(column(captured, "channel").tolist(), [b["channel"] for b in exp])

    # verify-tier: model — pin-wired loopback master TX -> slave RX for stereo I2S and 4/8-slot
    # TDM: the transmitted beats appear as a contiguous run in the received ones (a master
    # whose first frame starts before its buffer is full sends one silent frame first).
    def test_loopback(self):
        prng = random.Random(4)
        for fmt, sw, slot, n in (("i2s", 24, 32, 2), ("left_justified", 16, 16, 2), ("tdm", 24, 32, 4), ("tdm", 16, 16, 8)):
            with self.subTest(fmt=fmt, n_channels=n):
                frames = frames_for(prng, 6, n, sw)
                top = Module()
                top.submodules.tx = LiteDSPI2STransmitter(data_width=24, sample_width=sw, slot_width=slot, n_channels=n,
                    fmt=fmt, mode="master", bclk_div=8, with_csr=False)
                top.submodules.rx = LiteDSPI2SReceiver(data_width=24, sample_width=sw, slot_width=slot, n_channels=n,
                    fmt=fmt, mode="slave", with_csr=False)
                top.comb += [top.rx.bclk.eq(top.tx.bclk), top.rx.lrck.eq(top.tx.lrck), top.rx.sdata.eq(top.tx.sdata)]
                captured = []
                def driver():
                    yield from push(top.tx.sink, beats_for(frames, sw))
                    for _ in range(3*n*slot*8):
                        yield
                run_simulation(top, [driver(),
                    stream_capture(top.rx.source, captured, 5*n, ["data", "channel"], seed=2, ready_rate=0.7)])
                got = list(zip(column(captured, "data", 24).tolist(), column(captured, "channel").tolist()))
                exp = [(b["data"], b["channel"]) for b in beats_for(frames, sw)]
                runs = [exp[f*n:f*n + 3*n] for f in range(3)]           # 3-frame runs (the slave
                self.assertTrue(any(got[k:k + 3*n] == run for run in runs # locks on the first LRCK
                                    for k in range(len(got))), f"{fmt}: {got[:4]}")   # transition).
                self.assertEqual(got[0][1], 0)

    def test_overrun(self):
        top = Module()
        top.submodules.tx = LiteDSPI2STransmitter(data_width=24, n_channels=2, fmt="i2s", mode="master", bclk_div=4, with_csr=False)
        top.submodules.rx = LiteDSPI2SReceiver(data_width=24, n_channels=2, fmt="i2s", mode="slave", with_csr=False)
        top.comb += [top.rx.bclk.eq(top.tx.bclk), top.rx.lrck.eq(top.tx.lrck), top.rx.sdata.eq(top.tx.sdata)]
        seen = {}
        def driver():
            yield from push(top.tx.sink, beats_for(frames_for(random.Random(5), 4, 2, 24), 24))
            for _ in range(4*2*32*4):
                yield
            seen["overrun"] = (yield top.rx.overrun)
            yield top.rx.clear.eq(1)
            yield
            yield top.rx.clear.eq(0)
            yield
            seen["cleared"] = (yield top.rx.overrun)
        run_simulation(top, driver())                                 # Source never read.
        self.assertEqual((seen["overrun"], seen["cleared"]), (1, 0))

    def test_invalid(self):
        for kwargs in ({"fmt": "bad"}, {"slot_width": 20}, {"bclk_div": 3}, {"sample_width": 40},
                       {"fmt": "tdm", "n_channels": 3}, {"n_channels": 4}, {"mode": "auto"}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPI2SReceiver(with_csr=False, **kwargs)
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPI2STransmitter(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
