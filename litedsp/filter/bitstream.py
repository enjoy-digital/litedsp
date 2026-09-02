#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Sinc^N decimator for 1-bit sigma-delta / PDM bitstreams.

Isolated sigma-delta modulators (motor-drive current sense) and PDM microphones deliver a
1-bit stream at the modulator clock; a cascaded-integrator-comb (sinc^N) filter turns it into
PCM samples at ``rate`` times lower rate. The block maps each bit to ``+1/-1`` and runs the
runtime-rate CIC (:class:`~litedsp.filter.cic.LiteDSPCICDecimatorRuntime`) with a 2-bit input
so the Hogenauer registers cost ``2 + N*log2(r_max)`` bits; the runtime ``rate``/``shift``
controls plus a static alignment shift map a 100 % density bitstream to full scale.
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common     import check, real_layout, saturated
from litedsp.filter.cic import LiteDSPCICDecimatorRuntime, _growth_bits

# Helpers ------------------------------------------------------------------------------------------

def bitstream_align(r_max, n_stages, diff_delay, data_width):
    """Static left shift aligning a ``+1/-1`` sinc^N output of maximum growth to ``data_width``."""
    return max(0, (data_width - 1) - _growth_bits(r_max, n_stages, diff_delay))

def bitstream_shift(rate, n_stages, diff_delay, data_width, r_max=None):
    """Rescale shift for :class:`LiteDSPBitstreamDecimator` at ``rate`` (full density = +FS).

    The sinc^N gain on a ``+1/-1`` input is ``(rate*diff_delay)**n_stages``; the shift brings
    it to ``2**(data_width-1)`` together with the block's static alignment (sized for
    ``r_max``). Rates far below ``r_max`` would need a negative shift and are clamped at 0
    (reduced output scale; choose ``r_max`` close to the rates in use).
    """
    if r_max is None:
        r_max = rate
    gain_bits = n_stages*math.log2(rate*diff_delay)
    return max(0, int(round(gain_bits)) - (data_width - 1)
        + bitstream_align(r_max, n_stages, diff_delay, data_width))

# Bitstream Decimator ------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBitstreamDecimator(LiteXModule):
    """1-bit sigma-delta / PDM bitstream -> PCM samples through a runtime-rate sinc^N decimator.

    ``sink.data`` is one modulator bit per beat (``1`` = +1, ``0`` = -1); ``source`` emits one
    signed ``data_width`` sample per ``rate`` bits, ``+FS`` for a 100 % density stream at the
    reset configuration (``rate = decimation``, ``shift = bitstream_shift(...)``). ``rate`` and
    ``shift`` are runtime controls sized for ``r_max`` (default: ``decimation``), exactly as
    for :class:`~litedsp.filter.cic.LiteDSPCICDecimatorRuntime` (``staged=True`` selects its
    timing-friendly architecture). Shared by the motor-control sigma-delta current sense and
    the audio PDM microphone receiver.

    Parameters
    ----------
    decimation : int
        Reset decimation rate (bits per output sample), >= 2.
    n_stages : int
        Sinc order N (integrator/comb stages): 3 for current sense, 4-5 for audio PDM.
    diff_delay : int
        Comb differential delay M (usually 1).
    r_max : int
        Maximum runtime rate the datapath is sized for (default: ``decimation``).
    staged : bool
        Use the register-chained, pipelined CIC architecture (needs ``rate >= 2*n_stages + 4``).
    """
    def __init__(self, data_width=24, decimation=64, n_stages=4, diff_delay=1, r_max=None,
        staged=False, with_csr=True):
        if r_max is None:
            r_max = decimation
        check(decimation >= 2, "expected decimation >= 2")
        check(r_max >= decimation, "expected r_max >= decimation")
        self.data_width = data_width
        self.decimation = decimation
        self.n_stages   = n_stages
        self.diff_delay = diff_delay
        self.r_max      = r_max
        self.align      = bitstream_align(r_max, n_stages, diff_delay, data_width)
        self.sink   = stream.Endpoint([("data", 1)])               # Modulator bit.
        self.source = stream.Endpoint(real_layout(data_width))     # PCM sample.

        # # #

        # Runtime-rate sinc^N core on a 2-bit +1/-1 input.
        # ------------------------------------------------
        self.cic = cic = LiteDSPCICDecimatorRuntime(data_width=data_width, r_max=r_max,
            n_stages=n_stages, diff_delay=diff_delay, iq=False, staged=staged, in_width=2,
            with_csr=False)
        cic.rate.reset  = decimation
        cic.shift.reset = bitstream_shift(decimation, n_stages, diff_delay, data_width, r_max)
        self.rate, self.shift         = cic.rate, cic.shift
        self.sample_ce, self.out_ce   = cic.sample_ce, cic.out_ce
        self.latency = cic.latency
        pm1 = Signal((2, True))
        self.comb += [
            pm1.eq(Mux(self.sink.data, 1, -1)),
            cic.sink.valid.eq(self.sink.valid),
            cic.sink.first.eq(self.sink.first),
            cic.sink.last.eq(self.sink.last),
            cic.sink.data.eq(pm1),
            self.sink.ready.eq(cic.sink.ready),
        ]

        # Output alignment (static left shift, saturated: full density = +FS).
        # -------------------------------------------------------------------
        aligned = Signal((data_width + self.align + 1, True))
        self.comb += [
            aligned.eq(cic.source.data << self.align),
            self.source.valid.eq(cic.source.valid),
            self.source.first.eq(cic.source.first),
            self.source.last.eq(cic.source.last),
            self.source.data.eq(saturated(aligned, data_width)),
            cic.source.ready.eq(self.source.ready),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._rate  = CSRStorage(len(self.rate), reset=self.rate.reset.value, name="rate",
            description="Decimation rate (bits per output sample, 2..r_max).")
        self._shift = CSRStorage(len(self.shift), reset=self.shift.reset.value, name="shift",
            description="Rescale shift; set to bitstream_shift(rate, ...) for the chosen rate.")
        self.comb += [self.rate.eq(self._rate.storage), self.shift.eq(self._shift.storage)]
