#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import *

from litedsp.motor.encoder import LiteDSPQuadratureDecoder, LiteDSPHallDecoder

from test.models import quadrature_decoder_model, hall_sector_model

AW     = 16
GRAY   = [0b00, 0b01, 0b11, 0b10]                   # (a, b) forward sequence.
SECTOR = (1 << AW)//6

def quadrature_pins(segments, tail=12):
    """Pin arrays from (n_steps, cycles_per_step) segments (negative steps = backwards).
    Returns (a, b) per cycle, starting from state 0 with a leading idle cycle and ``tail``
    idle cycles at the end (synchronizer + filter drain)."""
    a, b, state = [0], [0], 0
    for n_steps, cps in segments:
        for _ in range(abs(n_steps)):
            state = (state + (1 if n_steps > 0 else -1)) % 4
            a += [GRAY[state] & 1]*cps
            b += [(GRAY[state] >> 1) & 1]*cps
    a += [a[-1]]*tail
    b += [b[-1]]*tail
    return np.array(a), np.array(b)

def drive(dut, pins):
    """Write pin arrays so value t is visible at cycle t (written the cycle before)."""
    n = max(len(v) for v in pins.values())
    def gen():
        for t in range(1, n):
            for name, values in pins.items():
                yield getattr(dut, name).eq(int(values[t]))
            yield
    return gen()

def record(dut, names, n, log):
    @passive
    def gen():
        for _ in range(n):
            row = []
            for name in names:
                row.append((yield getattr(dut, name)))
            log.append(tuple(row))
            yield
    return gen()

def capture_angles(dut, log):
    @passive
    def gen():
        yield dut.source.ready.eq(1)
        while True:
            if (yield dut.source.valid):
                log.append((yield dut.source.angle) & ((1 << AW) - 1))
            yield
    return gen()

class TestQuadratureDecoder(unittest.TestCase):
    def build(self, **kwargs):
        opts = dict(angle_width=AW, position_width=16, filter_length=2, with_csr=False)
        opts.update(kwargs)
        return LiteDSPQuadratureDecoder(**opts)

    # verify-tier: model — synchronizers, glitch filter, 4x decode, modular position and
    # electrical position, direction and error, cycle-exact over forward/backward motion with
    # a filtered 1-cycle glitch on A (rejected by filter_length = 2).
    def test_position_direction_bit_exact(self):
        a, b = quadrature_pins([(300, 7), (-200, 5), (50, 3)])
        a[1000] ^= 1                                          # 1-cycle glitch: filtered out.
        z = np.zeros(len(a), np.int64)
        dut = self.build()
        dut.counts_per_rev.reset, dut.pole_pairs.reset = 1000, 3
        log = []
        run_simulation(dut, [drive(dut, {"a": a, "b": b}),
            record(dut, ["position", "epos", "direction", "error"], len(a) - 1, log)])
        got = np.array(log)
        ref = quadrature_decoder_model(a, b, z, counts_per_rev=1000, pole_pairs=3)
        for k, name in enumerate(("position", "epos", "direction", "error")):
            self.assertTrue(np.array_equal(got[:, k], ref[name][:len(got)]), name)
        self.assertEqual(int(got[-1, 0]), (300 - 200 + 50) % 1000)   # Net +150 counts.
        self.assertEqual(int(got[-1, 3]), 0)                          # No error: glitch filtered.

    # verify-tier: bound — angle = epos*2**AW/cpr (+ offset) within 1 LSB for a power-of-two
    # and a non-power-of-two count (reciprocal multiply with 16 fractional bits: error <
    # cpr/2**16 turns of the LSB); sampled on the strobe, and cycle-exact vs the model. The
    # registered multiply makes the angle follow ``epos`` one cycle later.
    def test_angle_scaling(self):
        for cpr in (4096, 1000):
            with self.subTest(cpr=cpr):
                a, b = quadrature_pins([(cpr//2 + 37, 3)])
                n = len(a)
                sample = np.zeros(n, np.int64)
                sample[10::97] = 1
                dut = self.build()
                dut.counts_per_rev.reset, dut.pole_pairs.reset = cpr, 2
                dut.angle_scale.reset  = (1 << (AW + 16))//cpr
                dut.angle_offset.reset = 1234
                angles, log = [], []
                run_simulation(dut, [drive(dut, {"a": a, "b": b, "sample": sample}),
                    record(dut, ["epos"], n - 1, log), capture_angles(dut, angles)])
                ref = quadrature_decoder_model(a, b, np.zeros(n), counts_per_rev=cpr, pole_pairs=2,
                    angle_scale=(1 << (AW + 16))//cpr, angle_offset=1234)
                strobes = np.nonzero(sample[:n - 1])[0]
                self.assertTrue(
                    np.array_equal(np.array(angles[:len(strobes)]), ref["angle"][strobes]))
                epos  = ref["epos"][strobes - 1]
                truth = (epos*(1 << AW)/cpr + 1234) % (1 << AW)
                err   = (np.array(angles[:len(strobes)]) - truth + (1 << (AW - 1))) % (1 << AW) - (
                    1 << (AW - 1))
                self.assertLessEqual(np.max(np.abs(err)), 1.0)

    def test_index_zeroing_and_irq(self):
        a, b = quadrature_pins([(37, 4), (20, 4)])
        z = np.zeros(len(a), np.int64)
        z[37*4 + 2:37*4 + 8] = 1                              # Index pulse during count 38.
        for enable, expect in ((1, 19), (0, 57)):             # Zeroed after 38, then 19 more.
            with self.subTest(index_enable=enable):
                dut = self.build(with_irq=True)
                dut.index_enable.reset = enable
                log = []
                run_simulation(dut, [drive(dut, {"a": a, "b": b, "z": z}),
                    record(dut, ["position", "index_seen"], len(a) - 1, log)])
                got = np.array(log)
                self.assertEqual(int(got[-1, 0]), expect)
                self.assertEqual(int(got[-1, 1]), enable)
                ref = quadrature_decoder_model(a, b, z, index_enable=bool(enable))
                self.assertTrue(np.array_equal(got[:, 0], ref["position"][:len(got)]))

    def test_glitch_filter_and_error(self):
        # A simultaneous 1-cycle glitch on A and B (mid-step) is an illegal transition there
        # and back: flagged with filter_length = 1, filtered out with filter_length = 2, the
        # position is unaffected in both cases.
        a, b = quadrature_pins([(10, 6)])
        a[28] ^= 1
        b[28] ^= 1
        for fl, err in ((1, 1), (2, 0)):
            with self.subTest(filter_length=fl):
                dut = self.build(filter_length=fl)
                log = []
                run_simulation(dut, [drive(dut, {"a": a, "b": b}),
                    record(dut, ["position", "error"], len(a) - 1, log)])
                self.assertEqual(int(log[-1][0]), 10)
                self.assertEqual(int(log[-1][1]), err)

    # verify-tier: bound — M-method speed: 4 cycles per count with a 100-cycle window gives
    # 25 counts per window (+/-1 for window/step phase), sign follows the direction.
    def test_speed_window(self):
        a, b = quadrature_pins([(150, 4), (-150, 4)])
        dut = self.build()
        dut.window.reset = 100
        log = []
        run_simulation(dut, [drive(dut, {"a": a, "b": b}), record(dut, ["speed"], len(a) - 1, log)])
        speed = np.array([s - (1 << 16) if s >= (1 << 15) else s for (s,) in log])
        self.assertTrue(np.all(np.abs(speed[300:550] - 25) <= 1))
        self.assertTrue(np.all(np.abs(speed[950:1150] + 25) <= 1))

    def test_invalid(self):
        for kwargs in ({"filter_length": 0}, {"scale_frac": 0}, {"position_width": 1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPQuadratureDecoder(with_csr=False, **kwargs)

class TestHallDecoder(unittest.TestCase):
    FORWARD = [0b001, 0b011, 0b010, 0b110, 0b100, 0b101]

    def hall_pins(self, codes, cycles_per_sector):
        pins = [0]
        for c in codes:
            pins += [c]*cycles_per_sector
        return np.array(pins)

    def run_hall(self, hall, sample=None, log_names=("sector", "direction", "error"), **kwargs):
        opts = dict(angle_width=AW, timer_width=16, filter_length=2, with_csr=False)
        opts.update(kwargs)
        dut = LiteDSPHallDecoder(**opts)
        pins = {"hall": hall}
        if sample is not None:
            pins["sample"] = sample
        log, angles = [], []
        run_simulation(dut, [drive(dut, pins), record(dut, list(log_names), len(hall) - 1, log),
            capture_angles(dut, angles)])
        return dut, np.array(log), np.array(angles)

    # verify-tier: model — sector table, direction from the sequence, sticky error on the
    # invalid codes (0/7) after the synchronizer/filter delay.
    def test_sector_table_and_direction(self):
        codes = self.FORWARD*2 + self.FORWARD[::-1]*2 + [0b000, 0b101]
        hall  = self.hall_pins(codes, 20)
        _, log, _ = self.run_hall(hall)
        sec, dirn, err = hall_sector_model(codes)
        # Compare near the end of every code slot (decode delay 2 + filter_length + 1 cycles).
        idx = [(k + 1)*20 - 2 for k in range(len(codes))]
        self.assertTrue(np.array_equal(log[idx, 0], sec))
        self.assertTrue(np.array_equal(log[idx, 1], dirn))
        self.assertTrue(np.array_equal(log[idx, 2], err))

    # verify-tier: bound — constant speed (200 cycles per sector): from the third sector on
    # the interpolated angle tracks the true ramp within SECTOR/8 (7.5 degrees electrical;
    # the ramp restarts at each edge from the measured period, one edge of latency), and
    # the speed readback equals SECTOR*256/200 within 2 %.
    def test_interpolated_angle_tracks_truth(self):
        P     = 200
        codes = self.FORWARD*4
        hall  = self.hall_pins(codes, P)
        n     = len(hall)
        sample = np.zeros(n, np.int64)
        sample[5::13] = 1
        dut, log, angles = self.run_hall(hall, sample, log_names=("sector", "speed"))
        strobes = np.nonzero(sample[:n - 1])[0]
        lag     = 2 + 2 + 1                                    # Sync + filter + register.
        truth   = ((strobes - 1 - lag)/P*SECTOR) % (1 << AW)   # Ramp from code 0 at cycle 1.
        keep    = strobes > 1 + 2*P + lag                      # After two measured sectors.
        err     = (angles[:len(strobes)] - truth + (1 << (AW - 1))) % (1 << AW) - (1 << (AW - 1))
        self.assertLess(np.max(np.abs(err[keep])), SECTOR/8)
        speed   = log[-1, 1]
        self.assertLess(abs(speed - SECTOR*256/P), 0.02*SECTOR*256/P)

    def test_backward_and_center_modes(self):
        P     = 100
        codes = self.FORWARD[::-1]*3
        hall  = self.hall_pins(codes, P)
        n     = len(hall)
        sample = np.zeros(n, np.int64)
        sample[3::7] = 1
        # Interpolated, backwards: the angle decreases inside each sector.
        _, log, angles = self.run_hall(hall, sample, log_names=("sector", "direction"))
        self.assertEqual(int(log[-1, 1]), 1)
        d = np.diff(angles[-40:])
        self.assertTrue(np.all((d <= 0) | (d > SECTOR)))        # Decreasing (modulo wraps).
        # Center mode: the angle is the sector center.
        _, log, angles = self.run_hall(hall, sample, interpolate=False)
        centers = {SECTOR*k + SECTOR//2 for k in range(6)}
        self.assertTrue(set(angles[10:].tolist()) <= centers)

    def test_stall_and_invalid(self):
        hall = self.hall_pins([0b001]*2, 400)                  # No edge for 800 cycles.
        dut, log, _ = self.run_hall(hall, log_names=("stall",), timer_width=8)
        self.assertEqual(int(log[-1, 0]), 1)
        for kwargs in ({"timer_width": 4}, {"interpolate": "yes"}, {"filter_length": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPHallDecoder(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
