#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Receiver front-end producing packed, framed words ready for a wide AXI-Stream/DMA sink.

Chain: ``DDC`` (tune + decimate) -> ``StreamFIFO`` (elastic buffer to absorb the decimator's
bursty output) -> ``StreamFramer`` (mark first/last every frame, -> AXI-Stream tlast) -> ``IQPack``
(pack four 16-bit I/Q samples into one 128-bit bus word). This is the shape of a real capture
path: per-sample DSP on the narrow side, wide packed packets on the bus side.

Run ``python3 examples/wideband_rx.py``.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litex.gen import LiteXModule

from litedsp.mixing.ddc      import DDC
from litedsp.stream.fifo     import StreamFIFO
from litedsp.stream.framing  import StreamFramer
from litedsp.stream.adapt    import IQPack

from test.common import run_stream, column

# Wideband RX --------------------------------------------------------------------------------------

class WidebandRX(LiteXModule):
    def __init__(self, data_width=16, decimation=4, frame_len=8, pack_ratio=4, lo_phase_inc=0):
        self.ddc    = DDC(data_width=data_width, decimation=decimation, method="cic", with_csr=False)
        self.fifo   = StreamFIFO(depth=32, data_width=data_width, with_csr=False)
        self.framer = StreamFramer(length=frame_len, data_width=data_width, with_csr=False)
        self.pack   = IQPack(ratio=pack_ratio, data_width=data_width)
        self.sink   = self.ddc.sink
        self.source = self.pack.source              # Wide packed words.
        self.comb += [
            self.ddc.nco.phase_inc.eq(lo_phase_inc),
            self.ddc.source.connect(self.fifo.sink),
            self.fifo.source.connect(self.framer.sink),
            self.framer.source.connect(self.pack.sink),
        ]

# Demo ---------------------------------------------------------------------------------------------

def main():
    data_width, decimation, frame_len, pack_ratio = 16, 4, 8, 4
    n = 4096

    lo_bin    = n//8
    phase_inc = (1 << 32)//(n//lo_bin)
    dut = WidebandRX(data_width=data_width, decimation=decimation, frame_len=frame_len,
        pack_ratio=pack_ratio, lo_phase_inc=phase_inc)
    dut.ddc.nco.phase_inc.reset = phase_inc

    t   = np.arange(n)
    sig = 12000*np.exp(2j*np.pi*lo_bin*t/n)
    samples = [{"i": int(round(sig.real[k])), "q": int(round(sig.imag[k]))} for k in range(n)]

    # n input -> n/decimation baseband samples -> /pack_ratio packed words.
    n_words = (n//decimation)//pack_ratio - 2     # Leave margin for fill transients.
    cap = run_stream(dut, samples, n_words, ["i", "q"], ["data"],
        sink_throttle=0.0, source_ready_rate=0.8)

    print(f"Wideband RX: {n} samples @fs -> DDC/{decimation} -> FIFO -> frame({frame_len})"
          f" -> pack x{pack_ratio}")
    print(f"  produced {len(cap)} packed words of {2*data_width*pack_ratio} bits")
    assert len(cap) == n_words
    print("  PASS: DDC -> StreamFIFO -> StreamFramer -> IQPack streams wide packed packets")

if __name__ == "__main__":
    main()
