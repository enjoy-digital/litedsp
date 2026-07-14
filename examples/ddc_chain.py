#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Minimal digital down-converter (DDC) example assembled from LiteDSP blocks.

Chain: NCO (local oscillator) -> Mixer (down-conversion) -> FIRFilterComplex (low-pass) ->
Downsampler (decimation). This shows the standardized streaming/control contract in action:
all sub-blocks are built with ``with_csr=False`` and wired together by ``connect()``, with the
NCO/mixer/decimation controls driven directly.

Run ``python3 examples/ddc_chain.py`` to simulate it on a complex tone and print the result.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common            import iq_layout
from litedsp.generation.nco    import LiteDSPNCO
from litedsp.mixing.mixer      import LiteDSPMixer, MIXER_MODE_DOWN
from litedsp.filter.fir        import LiteDSPFIRFilterComplex
from litedsp.rate.dropper      import LiteDSPDownsampler

from test.common import run_stream, column

# DDC ----------------------------------------------------------------------------------------------

class LiteDSPDDC(LiteXModule):
    """NCO + Mixer(down) + low-pass FIR + Downsampler."""
    def __init__(self, data_width=16, n_taps=33, decimation=4, lo_phase_inc=0, coefficients=None):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.nco   = LiteDSPNCO(data_width=data_width, with_csr=False)
        self.mixer = LiteDSPMixer(data_width=data_width, with_csr=False)
        self.fir   = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=data_width,
            coefficients=coefficients, with_csr=False)
        self.deci  = LiteDSPDownsampler(data_width=data_width, with_csr=False)

        self.comb += [
            self.nco.phase_inc.eq(lo_phase_inc),
            self.mixer.mode.eq(MIXER_MODE_DOWN),
            self.deci.factor.eq(decimation),
            # sink -> mixer.a, nco -> mixer.b, mixer -> fir -> deci -> source.
            self.sink.connect(self.mixer.sink_a),
            self.nco.source.connect(self.mixer.sink_b),
            self.mixer.source.connect(self.fir.sink),
            self.fir.source.connect(self.deci.sink),
            self.deci.source.connect(self.source),
        ]

# Demo ---------------------------------------------------------------------------------------------

def main():
    data_width = 16
    decimation = 4
    n          = 4096

    # Low-pass FIR (Hamming-windowed sinc) for anti-alias before decimation.
    n_taps = 33
    m      = np.arange(n_taps) - (n_taps - 1)/2
    h      = np.sinc(2*0.1*m)*np.hamming(n_taps)
    coeffs = [int(round(c*((1 << 15) - 1))) for c in (h/h.sum())]

    # Place the LO at +fs/8 so a tone at +fs/8 lands at DC after down-conversion.
    lo_bin   = n//8
    phase_inc = (1 << 32)//(n//lo_bin)

    dut = LiteDSPDDC(data_width=data_width, n_taps=n_taps, decimation=decimation,
        lo_phase_inc=phase_inc, coefficients=coeffs)
    dut.nco.phase_inc.reset = phase_inc

    # Input: complex tone at +fs/8 (should land at DC) + a tone at +3fs/8 (should be filtered).
    t   = np.arange(n)
    sig = 12000*np.exp(2j*np.pi*lo_bin*t/n) + 12000*np.exp(2j*np.pi*3*lo_bin*t/n)
    xi  = np.round(sig.real).astype(int)
    xq  = np.round(sig.imag).astype(int)
    samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(n)]

    captured = run_stream(dut, samples, n//decimation, ["i", "q"], ["i", "q"],
        sink_throttle=0.0, source_ready_rate=1.0)
    out = column(captured, "i", data_width) + 1j*column(captured, "q", data_width)
    out = out[n_taps:]  # Skip filter fill transient.

    # After down-conversion the wanted tone is at DC: its mean magnitude should dominate.
    dc_level = np.abs(out.mean())
    ac_level = np.std(out)
    print(f"DDC output: {len(out)} samples @ fs/{decimation}")
    print(f"  DC (down-converted tone) magnitude : {dc_level:8.1f}")
    print(f"  residual AC (rejected tone) std    : {ac_level:8.1f}")
    print(f"  rejection                          : {20*np.log10(dc_level/max(ac_level,1e-9)):6.1f} dB")

if __name__ == "__main__":
    main()
