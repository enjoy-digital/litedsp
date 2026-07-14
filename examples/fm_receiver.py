#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""FM receiver example: FM-discriminator demod followed by audio decimation.

    python3 examples/fm_receiver.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common         import iq_layout, real_layout
from litedsp.comm.fm_demod  import LiteDSPFMDemod
from litedsp.filter.fir_poly import LiteDSPFIRDecimator
from litedsp.filter.design  import firwin_lowpass

# FM receiver: FM demod -> low-pass decimate (audio). ----------------------------------------------

class FMReceiver(LiteXModule):
    def __init__(self, data_width=16, audio_decim=4):
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        self.demod = LiteDSPFMDemod(data_width=data_width, angle_width=data_width, with_csr=False)
        # Decimate the (real) demodulated signal: feed it as I, take I out.
        coeffs = firwin_lowpass(8*audio_decim + 1, 0.4/audio_decim, data_width=data_width)
        self.audio = LiteDSPFIRDecimator(n_taps=8*audio_decim + 1, decimation=audio_decim, data_width=data_width,
            coefficients=coeffs, with_csr=False)
        self.source = self.audio.source
        self.comb += [
            self.sink.connect(self.demod.sink),
            self.audio.sink.i.eq(self.demod.source.data),
            self.audio.sink.valid.eq(self.demod.source.valid),
            self.demod.source.ready.eq(self.audio.sink.ready),
            self.audio.sink.q.eq(0),
        ]

def main():
    n   = 8000
    fm  = 0.002
    msg = np.cos(2*np.pi*fm*np.arange(n))
    f_dev = 0.05
    x = 14000*np.exp(1j*2*np.pi*np.cumsum(f_dev*msg))    # FM-modulated carrier at baseband.

    dut = FMReceiver(data_width=16, audio_decim=4)
    samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
    cap = run_stream(dut, samples, n//4 - 20, ["i", "q"], ["i", "q"],
        sink_throttle=0.0, source_ready_rate=1.0)
    audio = to_signed(column(cap, "i"), 16).astype(float)   # demod audio is carried on I.
    # The decimated audio should track the (decimated) message tone.
    ref = np.cos(2*np.pi*(fm*4)*np.arange(len(audio)))
    c = max(abs(np.corrcoef(audio[5:], ref[5:5+len(audio)-5])[0, 1]) for _ in [0])
    print(f"FM receiver: demod + x4 audio decimation, {len(audio)} audio samples")
    print(f"  recovered-vs-message correlation: {c:.3f}")

from test.common import run_stream, column, to_signed

if __name__ == "__main__":
    main()
