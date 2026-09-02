#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.bitstream import LiteDSPBitstreamDecimator, bitstream_shift

from test.common import run_stream, column, assert_snr
from test.models import bitstream_decimator_model, sigma_delta_stimulus

class TestBitstreamDecimator(unittest.TestCase):
    def run_dec(self, bits, throttle=0.2, ready_rate=0.7, **kwargs):
        dut   = LiteDSPBitstreamDecimator(with_csr=False, **kwargs)
        n_out = len(bits)//dut.rate.reset.value
        cap   = run_stream(dut, [{"data": int(b)} for b in bits], n_out, ["data"], ["data"],
            sink_throttle=throttle, source_ready_rate=ready_rate)
        return dut, column(cap, "data", dut.data_width)

    # verify-tier: model — 2-bit +1/-1 sinc^N with the reset shift/alignment, bit-exact under
    # backpressure (16-bit current-sense and 24-bit audio configurations).
    def test_bit_exact(self):
        prng = random.Random(1)
        for kwargs in (dict(data_width=16, decimation=16, n_stages=3),
                       dict(data_width=24, decimation=64, n_stages=4),
                       dict(data_width=16, decimation=64, n_stages=3, r_max=256)):
            with self.subTest(**kwargs):
                bits = [prng.randint(0, 1) for _ in range(kwargs["decimation"]*40)]
                dut, got = self.run_dec(bits, **kwargs)
                ref = bitstream_decimator_model(bits, kwargs["decimation"], kwargs["n_stages"],
                    data_width=kwargs["data_width"], r_max=kwargs.get("r_max"))
                self.assertTrue(np.array_equal(got, ref[:len(got)]))
                self.assertEqual(dut.latency, 1)

    # verify-tier: bound — a bit density p maps to the level 2p - 1 (100 % = +FS): 60 % random
    # density -> +0.2 FS within 2 % of full scale (the sinc^4 averages 64-bit windows; the
    # random-walk spread of the density over 64 bits is ~6 %, so 1024 outputs are averaged).
    def test_density_maps_to_level(self):
        prng = random.Random(2)
        bits = [int(prng.random() < 0.6) for _ in range(64*1024)]
        _, got = self.run_dec(bits, throttle=0.0, ready_rate=1.0, data_width=24, decimation=64,
            n_stages=4)
        self.assertLess(abs(got[8:].mean()/(1 << 23) - 0.2), 0.02)
        ones = [1]*(64*40)
        _, full = self.run_dec(ones, throttle=0.0, ready_rate=1.0, data_width=24, decimation=64,
            n_stages=4)
        self.assertEqual(int(full[-1]), (1 << 23) - 1)          # 100 % density saturates at +FS.

    # verify-tier: bound — a -6 dBFS tone through a 2nd-order sigma-delta at OSR 64 and the
    # sinc^4 (24-bit) recovers >= 45 dB SNR at the output rate (2nd-order noise shaping at
    # OSR 64 leaves ~-75 dB in-band; the sinc^4 droop at fs_out/64 is < 0.01 dB). The tone is
    # least-squares fitted at the known frequency (the sinc^4 group delay of ~N*R/2 bits is a
    # pure phase shift); measured SNR at LITEDSP_SEED=0 noted below, gate 45 dB.
    def test_sigma_delta_loopback_snr(self):
        R, n_out = 64, 512
        t    = np.arange(R*n_out)
        x    = 0.5*np.sin(2*np.pi*t/(R*64))                         # fs_out/64.
        bits = sigma_delta_stimulus(x)
        _, got = self.run_dec(bits, throttle=0.0, ready_rate=1.0, data_width=24, decimation=R,
            n_stages=4)
        y   = got[16:].astype(float)
        k   = np.arange(len(y))
        A   = np.stack([np.cos(2*np.pi*k/64), np.sin(2*np.pi*k/64), np.ones(len(y))], axis=1)
        fit = A @ np.linalg.lstsq(A, y, rcond=None)[0]
        amp = np.hypot(*np.linalg.lstsq(A, y, rcond=None)[0][:2])
        snr = 10*np.log10(np.sum(fit**2)/np.sum((y - fit)**2))
        self.assertGreaterEqual(snr, 45.0, f"sigma-delta loopback: SNR {snr:.1f} dB")
        self.assertLess(abs(amp/(1 << 23) - 0.5), 0.005)            # Amplitude within 1 %.

    # verify-tier: model — non-power-of-two and staged variants (the staged CIC carries an
    # n_stages-bit group delay, as its own tests document).
    def test_rate_sweep_and_staged(self):
        prng = random.Random(3)
        for R, N, staged in ((8, 2, False), (100, 3, False), (256, 4, False), (32, 3, True)):
            with self.subTest(R=R, N=N, staged=staged):
                bits = [prng.randint(0, 1) for _ in range(R*30)]
                dut, got = self.run_dec(bits, data_width=16, decimation=R, n_stages=N, staged=staged)
                ref = bitstream_decimator_model(bits, R, N, data_width=16, staged=staged)
                self.assertTrue(np.array_equal(got, ref[:len(got)]))

    def test_invalid(self):
        for kwargs in ({"decimation": 1}, {"r_max": 8}, {"n_stages": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPBitstreamDecimator(with_csr=False, **kwargs)
        self.assertEqual(bitstream_shift(64, 3, 1, 16, 256), 3)   # 2**18 gain -> Q1.15.

if __name__ == "__main__":
    unittest.main()
