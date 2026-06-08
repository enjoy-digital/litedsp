#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.generation.nco  import NCO
from litedsp.mixing.mixer    import Mixer, MIXER_MODE_UP
from litedsp.rate.interpolator import Interpolator

# Digital Up-Converter -----------------------------------------------------------------------------

class DUC(LiteXModule):
    """Digital up-converter: interpolator + complex mixer (up) + NCO.

    Interpolates a baseband I/Q stream up to the high rate and shifts it to the NCO frequency.
    Tuning word is the NCO ``phase_inc`` CSR. Canonical TX chain.
    """
    def __init__(self, data_width=16, interpolation=8, method="cic", phase_bits=32, with_csr=True):
        self.data_width    = data_width
        self.interpolation = interpolation
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.interp = Interpolator(data_width=data_width, factor=interpolation, method=method,
            with_csr=with_csr)
        self.nco    = NCO(phase_bits=phase_bits, data_width=data_width, with_csr=with_csr)
        self.mixer  = Mixer(data_width=data_width, with_csr=False)
        self.latency = self.interp.latency
        self.comb += [
            self.mixer.mode.eq(MIXER_MODE_UP),
            self.sink.connect(self.interp.sink),
            self.interp.source.connect(self.mixer.sink_a),
            self.nco.source.connect(self.mixer.sink_b),
            self.mixer.source.connect(self.source),
        ]
