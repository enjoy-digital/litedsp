#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common                  import iq_layout
from litedsp.generation.nco_parallel import ParallelNCO
from litedsp.mixing.mixer            import MIXER_MODE_DOWN
from litedsp.mixing.mixer_parallel   import ParallelMixer
from litedsp.filter.cic_parallel     import ParallelCICDecimator

# Parallel DDC ---------------------------------------------------------------------------------------

@ResetInserter()
class ParallelDDC(LiteXModule):
    """Digital down-converter for multi-sample front-ends (rates above the fabric clock).

    ``n_samples`` I/Q samples enter per beat (e.g. from a gigasample ADC through
    ``IQSerialToParallel``/serdes capture); a :class:`ParallelNCO` + :class:`ParallelMixer`
    tune the band to baseband and a :class:`ParallelCICDecimator` (``decimation`` a multiple of
    ``n_samples``) brings the rate back to at most one sample per cycle — the output is a
    standard serial I/Q stream, bit-identical to the serial NCO -> Mixer -> CIC chain. The
    tuning word is the NCO ``phase_inc`` CSR (set it to ``-f_tune`` in phase units).
    """
    def __init__(self, n_samples=4, data_width=16, decimation=8, cic_stages=3, phase_bits=32,
        with_csr=True):
        self.n_samples  = n_samples
        self.data_width = data_width
        self.decimation = decimation
        self.sink   = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.nco   = ParallelNCO(n_samples=n_samples, phase_bits=phase_bits,
            data_width=data_width, with_csr=with_csr)
        self.mixer = ParallelMixer(n_samples=n_samples, data_width=data_width, with_csr=False)
        self.decim = ParallelCICDecimator(n_samples=n_samples, data_width=data_width,
            R=decimation, N=cic_stages, with_csr=with_csr)
        self.latency = self.mixer.latency + self.decim.latency
        self.comb += [
            self.mixer.mode.eq(MIXER_MODE_DOWN),
            self.sink.connect(self.mixer.sink_a),
            self.nco.source.connect(self.mixer.sink_b),
            self.mixer.source.connect(self.decim.sink),
            self.decim.source.connect(self.source),
        ]
