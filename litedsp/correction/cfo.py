#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import iq_layout
from litedsp.generation.nco import LiteDSPNCO
from litedsp.mixing.mixer   import LiteDSPMixer, MIXER_MODE_DOWN

# Carrier / Frequency Offset Derotator -------------------------------------------------------------

class LiteDSPDerotator(LiteXModule):
    """Frequency-shift (derotate) an I/Q stream by ``-phase_inc`` (NCO + down-mixer).

    Use with a manual ``phase_inc`` (the NCO CSR) to correct a known CFO, or drive
    ``nco.phase_inc`` from a carrier-recovery loop. ``source = sink * exp(-j*2*pi*f*n)``.
    """
    def __init__(self, data_width=16, phase_bits=32, with_csr=True):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.nco   = LiteDSPNCO(phase_bits=phase_bits, data_width=data_width, with_csr=with_csr)
        self.mixer = LiteDSPMixer(data_width=data_width, with_csr=False)
        self.latency = self.mixer.latency                # NCO free-runs; only the mixer adds latency.
        self.comb += [
            self.mixer.mode.eq(MIXER_MODE_DOWN),         # a * conj(nco) = derotate by NCO freq.
            self.sink.connect(self.mixer.sink_a),
            self.nco.source.connect(self.mixer.sink_b),
            self.mixer.source.connect(self.source),
        ]
