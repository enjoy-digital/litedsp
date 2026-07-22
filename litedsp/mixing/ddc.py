#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common           import iq_layout
from litedsp.generation.nco   import LiteDSPNCO
from litedsp.mixing.mixer     import LiteDSPMixer, MIXER_MODE_DOWN
from litedsp.rate.decimator   import LiteDSPDecimator

# Digital Down-Converter ---------------------------------------------------------------------------

class LiteDSPDDC(LiteXModule):
    """Digital down-converter: NCO + complex mixer (down) + decimator.

    Tunes a band centered at the NCO frequency down to baseband and decimates. The tuning word
    is the NCO ``phase_inc`` CSR (set it to ``-f_tune`` in phase units). Canonical RX front-end.
    """
    def __init__(self, data_width=16, decimation=8, method="cic", phase_bits=32, with_csr=True,
        fir_architecture="classic"):
        self.data_width = data_width
        self.decimation = decimation
        self.sink   = stream.Endpoint(iq_layout(data_width))  # High-rate I/Q input.
        self.source = stream.Endpoint(iq_layout(data_width))  # Baseband I/Q output (rate/decimation).

        # # #

        # Submodules.
        # -----------
        self.nco   = LiteDSPNCO(phase_bits=phase_bits, data_width=data_width, with_csr=with_csr)
        self.mixer = LiteDSPMixer(data_width=data_width, with_csr=False)  # Mode hardwired below.
        self.decim = LiteDSPDecimator(data_width=data_width, decimation=decimation, method=method,
            with_csr=with_csr, fir_architecture=fir_architecture)
        self.latency = self.decim.latency

        # Datapath.
        # ---------
        self.comb += [
            self.mixer.mode.eq(MIXER_MODE_DOWN),  # sink * conj(nco): shift down to baseband.
            self.sink.connect(self.mixer.sink_a),
            self.nco.source.connect(self.mixer.sink_b),
            self.mixer.source.connect(self.decim.sink),
            self.decim.source.connect(self.source),
        ]
