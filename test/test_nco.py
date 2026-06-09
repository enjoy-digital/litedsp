#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.generation.nco import NCO

from test.common import run_stream, column
from test.models import nco_model

def _to_signed(values, width):
    values = np.asarray(values, dtype=np.int64) & ((1 << width) - 1)
    return np.where(values >= (1 << (width-1)), values - (1 << width), values)

class TestNCO(unittest.TestCase):
    def nco_case(self, phase_inc, phase_bits=32, data_width=16, lut_depth=1024, n=200, quarter_wave=False):
        dut = NCO(phase_bits=phase_bits, data_width=data_width, lut_depth=lut_depth,
            quarter_wave=quarter_wave, with_csr=False)
        dut.phase_inc.reset = phase_inc  # Stable from cycle 0 (mirrors a CSR set before streaming).

        captured = run_stream(dut,
            sink_samples = None,                  # Source-only block.
            n_out        = n,
            sink_fields  = None,
            source_fields = ["i", "q"],
            source_ready_rate = 0.7,
        )
        got_i = _to_signed(column(captured, "i"), data_width)
        got_q = _to_signed(column(captured, "q"), data_width)
        ref_i, ref_q = nco_model(phase_inc, n, phase_bits, data_width, lut_depth)
        return got_i, got_q, ref_i, ref_q

    def test_bit_exact(self):
        # Several increments incl. ones that wrap the accumulator.
        for phase_inc in [(1 << 32)//1024, 0x01234567, 0x0fffffff, 0x80000001]:
            got_i, got_q, ref_i, ref_q = self.nco_case(phase_inc)
            self.assertTrue(np.array_equal(got_i, ref_i), f"I mismatch @inc={phase_inc:#x}")
            self.assertTrue(np.array_equal(got_q, ref_q), f"Q mismatch @inc={phase_inc:#x}")

    def test_quarter_wave_bit_exact(self):
        # Quarter-wave reconstruction must be bit-identical to the full-LUT model.
        for phase_inc in [(1 << 32)//1024, 0x01234567, 0x0fffffff]:
            got_i, got_q, ref_i, ref_q = self.nco_case(phase_inc, quarter_wave=True)
            self.assertTrue(np.array_equal(got_i, ref_i), f"QW I mismatch @inc={phase_inc:#x}")
            self.assertTrue(np.array_equal(got_q, ref_q), f"QW Q mismatch @inc={phase_inc:#x}")

    def test_spectral_purity(self):
        # Bin-aligned tone (coherent sampling, no window): the worst spur must be well down.
        n         = 1024
        bin_tone  = 16
        phase_inc = (1 << 32)//(n//bin_tone)  # f = fs * bin_tone/n.
        got_i, got_q, _, _ = self.nco_case(phase_inc, n=n)
        spec = np.abs(np.fft.fft(got_i + 1j*got_q))**2
        peak = spec[bin_tone]
        spec[bin_tone] = 0
        sfdr = 10*np.log10(peak/spec.max())
        self.assertGreater(sfdr, 60.0, f"SFDR too low: {sfdr:.1f} dB")

if __name__ == "__main__":
    unittest.main()
