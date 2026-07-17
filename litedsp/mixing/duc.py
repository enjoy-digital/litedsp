#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.generation.nco  import LiteDSPNCO
from litedsp.mixing.mixer    import LiteDSPMixer, MIXER_MODE_UP
from litedsp.rate.interpolator import LiteDSPInterpolator

# Digital Up-Converter -----------------------------------------------------------------------------

class LiteDSPDUC(LiteXModule):
    """Digital up-converter: interpolator + complex mixer (up) + NCO.

    Interpolates a baseband I/Q stream up to the high rate and shifts it to the NCO frequency.
    Tuning word is the NCO ``phase_inc`` CSR. Canonical TX chain.
    """
    def __init__(self, data_width=16, interpolation=8, method="cic", phase_bits=32,
        with_csr=True, fir_architecture="classic"):
        self.data_width    = data_width
        self.interpolation = interpolation
        self.sink   = stream.Endpoint(iq_layout(data_width))  # Baseband I/Q input.
        self.source = stream.Endpoint(iq_layout(data_width))  # High-rate I/Q output (rate*interpolation).

        # # #

        # Submodules.
        # -----------
        self.interp = LiteDSPInterpolator(data_width=data_width, interpolation=interpolation, method=method,
            with_csr=with_csr, fir_architecture=fir_architecture)
        self.nco    = LiteDSPNCO(phase_bits=phase_bits, data_width=data_width, with_csr=with_csr)
        self.mixer  = LiteDSPMixer(data_width=data_width, with_csr=False)  # Mode hardwired below.
        self.latency = self.interp.latency

        # Datapath.
        # ---------
        self.comb += [
            self.mixer.mode.eq(MIXER_MODE_UP),  # sink * nco: shift up to the NCO frequency.
            self.sink.connect(self.interp.sink),
            self.interp.source.connect(self.mixer.sink_a),
            self.nco.source.connect(self.mixer.sink_b),
            self.mixer.source.connect(self.source),
        ]
