#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the host-side drivers (litedsp/software/drivers.py) against a mock register map."""

import unittest

from litedsp.software.drivers import (phase_inc_from_freq, freq_from_phase_inc, discover,
    NCODriver, CaptureDriver, CSRReaderDriver, DMADriver, FIRDriver, GainDriver, MixerDriver)

# Mock bus -----------------------------------------------------------------------------------------

class MockCSR:
    def __init__(self, value=0):
        self.value  = value
        self.writes = []

    def read(self):
        v = self.value
        if isinstance(v, list):                            # Scripted read sequence.
            v = v.pop(0) if len(v) > 1 else v[0]
        return v

    def write(self, value):
        self.writes.append(value)
        if not isinstance(self.value, list):
            self.value = value

class MockRegs:
    pass

class MockBus:
    def __init__(self, regs):
        self.regs = MockRegs()
        for name, csr in regs.items():
            setattr(self.regs, name, csr)

# Tests --------------------------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    def test_phase_inc_round_trip(self):
        clk = 100e6
        for f in (1e6, -1e6, 12.345e6, 0.0):
            inc = phase_inc_from_freq(f, clk)
            self.assertLess(abs(freq_from_phase_inc(inc, clk) - f), clk/2**31)

class TestNCODriver(unittest.TestCase):
    def test_tune(self):
        bus = MockBus({"nco_phase_inc": MockCSR()})
        nco = NCODriver(bus, "nco", clk_freq=100e6)
        nco.set_frequency(25e6)
        self.assertEqual(bus.regs.nco_phase_inc.writes, [1 << 30])   # fs/4.
        self.assertAlmostEqual(nco.get_frequency(), 25e6)

class TestCaptureDriver(unittest.TestCase):
    def test_trigger_and_status(self):
        bus = MockBus({"cap_threshold": MockCSR(), "cap_force": MockCSR(),
                       "cap_status": MockCSR(0b10)})
        cap = CaptureDriver(bus, "cap")
        cap.trigger()
        self.assertEqual(bus.regs.cap_force.writes, [0, 1, 0])
        self.assertTrue(cap.done)
        self.assertFalse(cap.armed)

class TestCSRReaderDriver(unittest.TestCase):
    def test_read_signed_samples(self):
        # Two samples: (1, -1), (-2, 2).
        words = [(1 & 0xFFFF) | ((-1 & 0xFFFF) << 16), (-2 & 0xFFFF) | ((2 & 0xFFFF) << 16)]
        bus = MockBus({"rd_data": MockCSR(list(words)), "rd_valid": MockCSR(1),
                       "rd_pop": MockCSR()})
        rd = CSRReaderDriver(bus, "rd")
        samples = rd.read_samples(2)
        self.assertEqual(samples, [complex(1, -1), complex(-2, 2)])
        self.assertEqual(bus.regs.rd_pop.writes, [1, 1])

class TestDMADriver(unittest.TestCase):
    def test_run(self):
        regs = {f"dma_writer_{r}": MockCSR() for r in DMADriver.regs}
        regs["dma_writer_done"].value = 1
        bus = MockBus(regs)
        dma = DMADriver(bus, "dma_writer")
        dma.run(base=0x40000000, length=4096)
        dma.wait_done()
        self.assertEqual(bus.regs.dma_writer_base.writes,   [0x40000000])
        self.assertEqual(bus.regs.dma_writer_length.writes, [4096])
        self.assertEqual(bus.regs.dma_writer_enable.writes, [0, 1])

class TestFIRDriver(unittest.TestCase):
    def test_load_taps(self):
        bus = MockBus({f"fir_coeff_{k}": MockCSR() for k in range(4)})
        fir = FIRDriver(bus, "fir")
        self.assertEqual(fir.n_taps, 4)
        fir.load([1, -1, 0.5, -0.5])
        self.assertEqual(bus.regs.fir_coeff_0.writes, [1])
        self.assertEqual(bus.regs.fir_coeff_1.writes, [-1 & 0xFFFF])
        self.assertEqual(bus.regs.fir_coeff_2.writes, [1 << 14])

class TestGainDriver(unittest.TestCase):
    def test_set_gain_and_saturation(self):
        bus = MockBus({"g0_gain": MockCSR(), "g0_control": MockCSR(), "g0_status": MockCSR(1)})
        g = GainDriver(bus, "g0")
        g.set_gain(2.0, shift=1)
        self.assertEqual(bus.regs.g0_gain.writes,    [2 << 14])   # 2.0 in Q2.14.
        self.assertEqual(bus.regs.g0_control.writes, [0b01])
        self.assertTrue(g.saturated)
        g.clear_saturation()
        self.assertEqual(bus.regs.g0_control.writes[-1] & (1 << 3), 1 << 3)

class TestMixerDriver(unittest.TestCase):
    def test_mode_and_bypass(self):
        bus = MockBus({"mix_control": MockCSR()})
        m = MixerDriver(bus, "mix")
        m.set_mode("up")
        self.assertEqual(bus.regs.mix_control.value & 0b1, 1)
        m.set_mode("down")
        self.assertEqual(bus.regs.mix_control.value & 0b1, 0)
        m.set_bypass(0b01)
        self.assertEqual((bus.regs.mix_control.value >> 8) & 0b11, 0b01)

class TestDiscover(unittest.TestCase):
    def test_discovers_blocks(self):
        regs = {"nco_phase_inc": MockCSR(), "ddc_nco_phase_inc": MockCSR(),
                "capture_threshold": MockCSR(), "capture_force": MockCSR(),
                "capture_status": MockCSR(),
                "reader_data": MockCSR(), "reader_valid": MockCSR(), "reader_pop": MockCSR(),
                "g0_gain": MockCSR(), "g0_control": MockCSR(), "g0_status": MockCSR(),
                "mix_control": MockCSR()}
        found = discover(MockBus(regs), clk_freq=100e6)
        self.assertIsInstance(found["nco"],     NCODriver)
        self.assertIsInstance(found["ddc_nco"], NCODriver)
        self.assertIsInstance(found["capture"], CaptureDriver)
        self.assertIsInstance(found["reader"],  CSRReaderDriver)
        self.assertIsInstance(found["g0"],      GainDriver)     # More specific than Mixer.
        self.assertIsInstance(found["mix"],     MixerDriver)
        self.assertEqual(len(found), 6)

if __name__ == "__main__":
    unittest.main()
