#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the host-side drivers (litedsp/software/drivers.py) against a mock register map."""

import unittest

from litedsp.software.drivers import (phase_inc_from_freq, freq_from_phase_inc, discover,
    NCODriver, CaptureDriver, CSRReaderDriver, DMADriver, FIRDriver, GainDriver, MixerDriver,
    FOCDriver, PWMDriver, QuadratureDecoderDriver,
    VolumeDriver, StereoMatrixDriver, CompressorDriver, AudioEQDriver, LFODriver, PeakMeterDriver,
    LoudnessDriver, RangeGateDriver, CFARDriver, OSCFARDriver, ClutterMapDriver, TargetListDriver, TrackerDriver, KalmanTrackerDriver, BeamformerDriver)

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

    def test_set_lowpass(self):
        from litedsp.filter.design import firwin_lowpass
        n_taps = 8
        bus = MockBus({f"fir_coeff_{k}": MockCSR() for k in range(n_taps)})
        fir = FIRDriver(bus, "fir")
        fir.set_lowpass(0.125)   # n_taps defaults to the coeff_<k> scan count.
        expected = firwin_lowpass(n_taps, 0.125, data_width=16)
        self.assertEqual(len(expected), n_taps)
        for k, t in enumerate(expected):
            self.assertEqual(getattr(bus.regs, f"fir_coeff_{k}").writes, [t & 0xFFFF])

    def test_set_lowpass_n_taps_mismatch(self):
        bus = MockBus({f"fir_coeff_{k}": MockCSR() for k in range(8)})
        fir = FIRDriver(bus, "fir")
        with self.assertRaises(AssertionError):
            fir.set_lowpass(0.125, n_taps=16)   # Explicit count must match the hardware.

    def test_set_remez(self):
        from litedsp.filter.design import remez_lowpass
        n_taps = 15
        bus = MockBus({f"fir_coeff_{k}": MockCSR() for k in range(n_taps)})
        fir = FIRDriver(bus, "fir")
        fir.set_remez(0.10, 0.20)
        expected = remez_lowpass(n_taps, 0.10, 0.20, data_width=16)
        self.assertEqual(len(expected), n_taps)
        for k, t in enumerate(expected):
            self.assertEqual(getattr(bus.regs, f"fir_coeff_{k}").writes, [t & 0xFFFF])

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

class TestMotorDrivers(unittest.TestCase):
    def test_foc_setpoints_gains_mode(self):
        regs = {f"foc_{r}": MockCSR() for r in FOCDriver.regs}
        drv  = FOCDriver(MockBus(regs), "foc")
        drv.set_setpoints(-0.25, 0.5)
        self.assertEqual(regs["foc_dq_setpoint_d"].value, (-8192) & 0xFFFF)
        self.assertEqual(regs["foc_dq_setpoint_q"].value, 16384)
        drv.set_gains(1.5, 0.02)
        self.assertEqual((regs["foc_dq_kp_d"].value, regs["foc_dq_ki_q"].value), (6144, 82))
        drv.set_open_loop(True, v_q=0.5)
        self.assertEqual(regs["foc_dq_voltage_q"].value, 16384)
        self.assertEqual(regs["foc_dq_control"].value & 1, 1)
        drv.set_open_loop(False)
        self.assertEqual(regs["foc_dq_control"].value & 1, 0)

    def test_pwm_frequency_dead_time(self):
        regs = {f"pwm_{r}": MockCSR() for r in PWMDriver.regs}
        drv  = PWMDriver(MockBus(regs), "pwm", clk_freq=100e6)
        drv.set_frequency(20e3)
        drv.set_dead_time(500e-9)
        drv.set_trigger(0, 1)
        drv.enable()
        self.assertEqual(regs["pwm_period"].value, 2500)
        self.assertEqual(regs["pwm_dead_time"].value, 50)
        self.assertEqual(regs["pwm_trigger"].value, 1 << 16)
        self.assertEqual(regs["pwm_control"].value & 1, 1)

    def test_quadrature_decoder_rpm(self):
        regs = {f"enc_{r}": MockCSR() for r in QuadratureDecoderDriver.regs}
        regs["enc_speed"].value = 100
        drv  = QuadratureDecoderDriver(MockBus(regs), "enc", clk_freq=100e6)
        drv.configure(4096, 4, window_cycles=1_000_000)
        self.assertEqual(regs["enc_angle_scale"].value, 1 << 20)
        # 100 counts per 10 ms window at 4096 counts/turn: 100/4096*100/s = 2.44 turns/s = 146 rpm.
        self.assertAlmostEqual(drv.get_speed_rpm(), 100/4096*100*60, places=6)

class TestAudioDrivers(unittest.TestCase):
    def test_volume_db_mute(self):
        regs = {f"vol_{r}": MockCSR() for r in VolumeDriver.regs + ("gain1",)}
        drv  = VolumeDriver(MockBus(regs), "vol")
        drv.set_db(0, 0.0)
        drv.set_db(1, -6.0206)
        self.assertEqual(regs["vol_gain0"].value, 1 << 19)
        self.assertEqual(regs["vol_gain1"].value, 1 << 18)
        drv.set_db(0, 40.0)                                        # Clamped to the register range.
        self.assertEqual(regs["vol_gain0"].value, (1 << 24) - 1)
        drv.mute(0b10)
        self.assertEqual(regs["vol_control"].value & 0xFF, 0b10)

    def test_stereo_matrix(self):
        regs = {f"mtx_{r}": MockCSR() for r in StereoMatrixDriver.regs}
        drv  = StereoMatrixDriver(MockBus(regs), "mtx")
        drv.ms_encode()
        self.assertEqual((regs["mtx_a"].value, regs["mtx_d"].value), (16384, (-16384) & 0x3FFFF))
        drv.swap()
        self.assertEqual((regs["mtx_a"].value, regs["mtx_b"].value), (0, 32768))

    def test_compressor_units(self):
        regs = {f"comp_{r}": MockCSR() for r in CompressorDriver.regs}
        drv  = CompressorDriver(MockBus(regs), "comp")
        drv.set_threshold_db(-6.0206)
        self.assertEqual(regs["comp_threshold"].value, (-256) & 0xFFFF)
        drv.set_ratio(4.0)
        self.assertEqual(regs["comp_slope_above"].value, 49152)
        drv.set_attack_ms(0)
        self.assertEqual(regs["comp_attack"].value, 65535)
        drv.set_release_ms(100.0, 48000)
        self.assertLess(regs["comp_release"].value, 65536//100)
        drv.set_detector(rms=True, rms_shift=5)
        self.assertEqual(regs["comp_control"].value & 0xFF, 1 | (5 << 4))
        regs["comp_status"].value = 512
        self.assertAlmostEqual(drv.gain_reduction_db, 12.04, places=1)

    def test_audio_eq_band_load(self):
        regs = {f"eq_{r}": MockCSR() for r in AudioEQDriver.regs}
        regs["eq_config"].value = 3 | (2 << 8) | (32 << 16) | (28 << 24)
        writes = []
        regs["eq_coeff_value"].write = lambda v: writes.append(v)
        drv  = AudioEQDriver(MockBus(regs), "eq")
        self.assertEqual((drv.n_bands, drv.coeff_width, drv.frac_bits), (3, 32, 28))
        drv.set_band(1, "peaking", 1000.0, -4.0, 1.5, sample_rate=48000)
        self.assertEqual(regs["eq_coeff_index"].value, 8)
        self.assertEqual(len(writes), 5)
        b0 = writes[0] if writes[0] < (1 << 31) else writes[0] - (1 << 32)
        self.assertAlmostEqual(b0/(1 << 28), 0.94, delta=0.05)     # Peaking b0 just below 1.
        drv.commit()
        self.assertEqual(regs["eq_control"].value & 1, 1)

    def test_lfo(self):
        regs = {f"lfo_{r}": MockCSR() for r in LFODriver.regs}
        drv  = LFODriver(MockBus(regs), "lfo", clk_freq=48000)
        drv.set_frequency(1.5)
        self.assertEqual(regs["lfo_phase_inc"].value, round(1.5/48000*2**32))
        drv.set_shape("saw")
        self.assertEqual(regs["lfo_control"].value & 0b11, 2)

    def test_meters(self):
        regs = {f"pm_{r}": MockCSR() for r in PeakMeterDriver.regs}
        regs["pm_peak_log20"].value = 23*256 - 256                # log2 = 22.0 -> -6.02 dBFS.
        regs["pm_peak0"].value = 1 << 22
        pm = PeakMeterDriver(MockBus(regs), "pm")
        self.assertAlmostEqual(pm.read_dbfs(0), -6.02, places=2)
        self.assertAlmostEqual(pm.read_peak(0), -6.02, places=2)
        regs = {f"lu_{r}": MockCSR() for r in LoudnessDriver.regs}
        regs["lu_config"].value = 2 | (24 << 4) | (4800 << 10)
        lu = LoudnessDriver(MockBus(regs), "lu")
        fs2 = float(1 << 46)
        # Two channels at -20 dBFS RMS: sum of mean squares = 2 * 0.01 -> -0.691 - 16.99 LKFS.
        regs["lu_hop_count"].value = 1
        regs["lu_sum_sq"].value = int(2*0.01*4800*fs2)
        lu.read_hop()
        self.assertAlmostEqual(lu.momentary(), -17.68, places=2)
        self.assertAlmostEqual(lu.integrated(), -17.68, places=2)

class TestRadarDrivers(unittest.TestCase):
    def test_range_gate(self):
        regs = {f"rg_{r}": MockCSR() for r in RangeGateDriver.regs}
        drv  = RangeGateDriver(MockBus(regs), "rg", clk_freq=10e6)
        drv.set_pri(100e-6)
        drv.set_gate(16, 64)
        drv.set_pulse(8, 32)
        drv.start()
        self.assertEqual(regs["rg_pri"].value, 1000)
        self.assertEqual(regs["rg_gate"].value, 16 | (64 << 24))
        self.assertEqual(regs["rg_pulse"].value, 8 | (32 << 24))
        self.assertEqual(regs["rg_control"].value, 1)
        drv.trigger()
        self.assertEqual(regs["rg_control"].value, 0b110)

    def test_cfar(self):
        from litedsp.radar.design import cfar_alpha
        regs = {f"cfar_{r}": MockCSR() for r in CFARDriver.regs}
        regs["cfar_config"].value = 8 | (2 << 8) | (8 << 16)
        drv  = CFARDriver(MockBus(regs), "cfar")
        drv.set_alpha(2.5)
        self.assertEqual(regs["cfar_alpha"].value, 640)
        drv.set_pfa(1e-3)
        self.assertEqual(regs["cfar_alpha"].value, cfar_alpha(1e-3, 16, "power", frac_bits=8))
        drv.set_mode("go")
        self.assertEqual(regs["cfar_control"].value, 1)
        regs["cfar_detections"].value = 7
        self.assertEqual(drv.detection_count, 7)
        drv.set_floor(40)
        self.assertEqual(regs["cfar_threshold_min"].value, 40)
        regs["cfar_config"].value = 68 | (8 << 16) | (1 << 24)    # 2-D box: n_training direct.
        drv.set_pfa(1e-3)
        self.assertEqual(regs["cfar_alpha"].value, cfar_alpha(1e-3, 68, "power", frac_bits=8))

    def test_os_cfar_and_clutter(self):
        regs = {f"os_{r}": MockCSR() for r in OSCFARDriver.regs}
        regs["os_config"].value = 4 | (2 << 8) | (8 << 16)
        drv = OSCFARDriver(MockBus(regs), "os")
        drv.set_rank(6)
        drv.set_alpha(3.0)
        self.assertEqual((regs["os_control"].value, regs["os_alpha"].value), (6, 768))
        with self.assertRaises(NotImplementedError):
            drv.set_pfa(1e-3)
        regs = {f"cm_{r}": MockCSR() for r in ClutterMapDriver.regs}
        regs["cm_config"].value = 64 | (3 << 20) | (8 << 24)
        drv = ClutterMapDriver(MockBus(regs), "cm")
        drv.set_alpha(2.5)
        drv.set_floor(30)
        drv.set_learning(learn_all=True)
        self.assertEqual((regs["cm_alpha"].value, regs["cm_threshold_min"].value, regs["cm_control"].value), (640, 30, 1))
        drv.clear()
        self.assertEqual(regs["cm_control"].value, 1 | (1 << 2))

    def test_kalman_tracker(self):
        regs = {f"kt_{r}": MockCSR() for r in KalmanTrackerDriver.regs}
        regs["kt_config"].value = 4 | (4 << 8) | (8 << 12) | (8 << 16)
        drv = KalmanTrackerDriver(MockBus(regs), "kt")
        drv.set_noise(0.05, 0.5)
        self.assertEqual(regs["kt_noise"].value, 13 | (128 << 16))
        drv.set_tracking_index(0.5)
        self.assertEqual(regs["kt_noise"].value, 32 | (128 << 16))
        with self.assertRaises(NotImplementedError):
            drv.set_gains(0.5, 0.1)
        regs["kt_cov_status"].value = 1
        self.assertEqual(drv.cov_sat, 1)
        drv.clear_cov_sat()
        self.assertEqual(regs["kt_cov"].value, 1)

    def test_beamformer(self):
        from litedsp.radar.design import steering_weights
        regs = {f"bf_{r}": MockCSR() for r in BeamformerDriver.regs}
        regs["bf_config"].value = 4 | (2 << 8) | (14 << 16)
        drv = BeamformerDriver(MockBus(regs), "bf")
        drv.set_steering(1, 20.0, 0.5, "hamming")
        re, im = steering_weights(4, 20.0, 0.5, "hamming", weight_frac=14)
        self.assertEqual(regs["bf_weight_index"].value, 1*4 + 3)
        self.assertEqual(regs["bf_weight"].value, (re[3] & 0xFFFF) | ((im[3] & 0xFFFF) << 16))
        self.assertEqual(len(regs["bf_weight"].writes), 4)
        drv.commit()
        self.assertEqual(regs["bf_control"].value, 1)

    def test_target_list(self):
        regs = {f"tl_{r}": MockCSR() for r in TargetListDriver.regs}
        regs["tl_config"].value = 16 | (4 << 16)
        regs["tl_count"].value  = 2
        table = {0: (0x0C8, 0x034, 500), 1: (0x1E4, 0x0B0, 900)}      # (12.5, 3.25), (30.25, 11.0).
        class Indexed(MockCSR):
            def __init__(self, k): self.k = k
            def read(self): return table[regs["tl_index"].value][self.k]
        regs["tl_range"], regs["tl_doppler"], regs["tl_data"] = Indexed(0), Indexed(1), Indexed(2)
        drv = TargetListDriver(MockBus(regs), "tl")
        self.assertEqual(drv.read_targets(), [
            {"range": 12.5, "doppler": 3.25, "data": 500}, {"range": 30.25, "doppler": 11.0, "data": 900}])
        regs["tl_status"].value = 1
        self.assertEqual(drv.overflow, 1)
        drv.clear()
        self.assertEqual(regs["tl_control"].value, 1)

    def test_tracker(self):
        regs = {f"trk_{r}": MockCSR() for r in TrackerDriver.regs}
        regs["trk_config"].value = 4 | (4 << 8) | (8 << 12) | (8 << 16)
        drv = TrackerDriver(MockBus(regs), "trk")
        drv.set_gains(0.5, 0.15)
        self.assertEqual(regs["trk_gains"].value, 128 | (38 << 16))
        drv.set_gates(2.0, 1.5)
        self.assertEqual(regs["trk_gates"].value, 32 | (24 << 16))
        drv.set_confirm(3, 2, emit_tentative=True)
        self.assertEqual(regs["trk_control"].value, 3 | (2 << 4) | (1 << 8))
        regs["trk_status"].value = 3 | (2 << 8)
        self.assertEqual((drv.active, drv.confirmed), (3, 2))
        from litedsp.radar.design import alpha_beta_from_index
        a, b = alpha_beta_from_index(0.5)
        drv.set_tracking_index(0.5)
        self.assertEqual(regs["trk_gains"].value, int(round(a*256)) | (int(round(b*256)) << 16))

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
