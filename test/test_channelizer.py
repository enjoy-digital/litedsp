#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import run_simulation

from litedsp.mixing.channelizer import LiteDSPChannelizer

from test.common import stream_driver, stream_capture, column

class TestChannelizer(unittest.TestCase):
    def test_separates_channels(self):
        for fir_architecture in ("classic", "pipelined"):
            with self.subTest(fir_architecture=fir_architecture):
                self._check_separates_channels(fir_architecture)

    def _check_separates_channels(self, fir_architecture):
        M = 4
        n = M*160
        k0 = 2                                            # Tone in channel 2.
        x = 12000*np.exp(1j*2*np.pi*(k0/M)*np.arange(n))
        dut = LiteDSPChannelizer(n_channels=M, decimation=M, data_width=16, method="fir",
            with_csr=False, fir_architecture=fir_architecture)

        samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
        n_out = n//M - 20
        caps = [[] for _ in range(M)]
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ["i", "q"], throttle=0.0),
            *[stream_capture(dut.sources[k], caps[k], n_out, ["i", "q"], seed=k, ready_rate=1.0)
              for k in range(M)],
        ])
        # Energy per channel (steady state).
        energy = []
        for k in range(M):
            y = column(caps[k], "i", 16) + 1j*column(caps[k], "q", 16)
            energy.append(np.mean(np.abs(y[len(y)//2:])**2))
        energy = np.array(energy)
        self.assertEqual(int(np.argmax(energy)), k0)
        others = np.delete(energy, k0)
        self.assertGreater(energy[k0], 20*others.max())

if __name__ == "__main__":
    unittest.main()
