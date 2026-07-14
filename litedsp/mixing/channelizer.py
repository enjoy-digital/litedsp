#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common       import iq_layout
from litedsp.stream.split import LiteDSPSplit
from litedsp.mixing.ddc   import LiteDSPDDC

# Channelizer (uniform DFT filterbank) -------------------------------------------------------------

class LiteDSPChannelizer(LiteXModule):
    """Split a wide band into ``n_channels`` uniformly-spaced sub-channels.

    Implemented as a bank of DDCs (one per channel, tuned to ``k/n_channels`` and decimated):
    correct, portable, and composed from tested blocks. ``self.sources[k]`` is sub-channel ``k``
    (baseband, decimated). Resource-optimal sharing via a polyphase-FIR + FFT structure is a
    documented future refinement.
    """
    def __init__(self, n_channels=4, decimation=None, data_width=16, method="fir",
        phase_bits=32, with_csr=True):
        if decimation is None:
            decimation = n_channels                       # Critically sampled.
        self.n_channels = n_channels
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        # Input Split.
        # ------------
        self.split = LiteDSPSplit(n=n_channels, data_width=data_width)
        self.comb += self.sink.connect(self.split.sink)

        # DDC Bank.
        # ---------
        self.ddcs    = []
        self.sources = []
        mask = (1 << phase_bits) - 1
        for k in range(n_channels):
            ddc = LiteDSPDDC(data_width=data_width, decimation=decimation, method=method,
                phase_bits=phase_bits, with_csr=False)
            ddc.nco.phase_inc.reset = int(round(k/n_channels*(1 << phase_bits))) & mask
            self.add_module(name=f"ddc{k}", module=ddc)
            self.comb += self.split.sources[k].connect(ddc.sink)
            self.ddcs.append(ddc)
            self.sources.append(ddc.source)
