#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common     import iq_layout, real_layout, real_lanes, scaled
from litedsp.filter.fir import _adder_tree, LiteDSPFIRCoefficients

# Parallel FIR Filter (real) -----------------------------------------------------------------------

class LiteDSPParallelFIRFilter(LiteXModule):
    """Real FIR over ``n_samples`` lanes per beat (multi-sample-per-cycle datapaths).

    Computes the same ``y[k] = sum_t coeffs[t] * x[k-t]`` as
    :class:`~litedsp.filter.fir.LiteDSPFIRFilter` on the flattened lane stream (lane 0 = first
    sample), producing ``n_samples`` outputs per beat with ``n_samples * n_taps`` multipliers
    and the same rounding/saturation and 3-cycle latency. The sample history advances only on
    real transfers (elastic pipeline), so backpressure never corrupts the convolution.
    """
    def __init__(self, n_samples=2, n_taps=32, data_width=16, shift=None):
        assert n_samples >= 1 and n_taps > 0
        if shift is None:
            shift = data_width - 1
        self.n_samples  = n_samples
        self.n_taps     = n_taps
        self.data_width = data_width
        self.latency    = 3
        self.sink   = stream.Endpoint(real_layout(data_width, n_samples))
        self.source = stream.Endpoint(real_layout(data_width, n_samples))
        self.coeffs = Array([Signal((data_width, True)) for _ in range(n_taps)])

        # # #

        # Handshake: drain when output can accept; consume an input on each drained beat.
        # -------------------------------------------------------------------------------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A real input beat is consumed this cycle.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            xfer.eq(self.sink.valid & adv),
            self.sink.ready.eq(adv),
        ]

        # Current beat lanes as signed samples (s[0] = first/oldest of the beat).
        # -----------------------------------------------------------------------
        s = [Signal((data_width, True)) for _ in range(n_samples)]
        for lane, sig in zip(real_lanes(self.sink, data_width, n_samples), s):
            self.comb += sig.eq(lane)

        # Sample window (w[m] = x[newest - m]), shifted by n_samples per real transfer —
        # the parallel equivalent of the serial FIR's shift register.
        # -----------------------------------------------------------
        w = [Signal((data_width, True)) for _ in range(n_taps - 1 + n_samples)]
        for m in range(len(w)):
            new = s[n_samples - 1 - m] if m < n_samples else w[m - n_samples]
            self.sync += If(xfer, w[m].eq(new))

        # Per-lane multiply (registered on drain) + adder tree + rescale.
        # ---------------------------------------------------------------
        acc_bits = 2*data_width + int(math.ceil(math.log2(n_taps))) + 1
        for j, o_lane in enumerate(real_lanes(self.source, data_width, n_samples)):
            prods = [Signal((2*data_width, True)) for _ in range(n_taps)]
            for t in range(n_taps):
                x = w[n_samples - 1 - j + t]                        # x[k+j-t] for output lane j.
                self.sync += If(adv, prods[t].eq(x*self.coeffs[t]))
            acc = Signal((acc_bits, True))
            self.comb += acc.eq(_adder_tree(list(prods)))
            result, _ = scaled(acc, shift, data_width)
            out = Signal((data_width, True))
            self.sync += If(adv, out.eq(result))
            self.comb += o_lane.eq(out)

        # Valid pipeline (matches the 3 register stages, drains on each beat).
        # --------------------------------------------------------------------
        valid_pipe = Signal(self.latency)
        self.sync += If(adv, valid_pipe.eq(Cat(self.sink.valid, valid_pipe[:-1])))
        self.comb += self.source.valid.eq(valid_pipe[-1])

# Parallel FIR Filter (complex) --------------------------------------------------------------------

@ResetInserter()
class LiteDSPParallelFIRFilterComplex(LiteXModule):
    """Complex parallel FIR: identical :class:`LiteDSPParallelFIRFilter` on I and Q, shared coefficients.

    The multi-sample ``i``/``q`` fields are the concatenated lanes, so they map one-to-one onto
    the real filters' multi-sample ``data`` fields. Coefficients are shared/CSR-reloadable via
    :class:`~litedsp.filter.fir.LiteDSPFIRCoefficients`, as in the serial complex FIR.
    """
    def __init__(self, n_samples=2, n_taps=32, data_width=16, coefficients=None, shift=None,
        with_csr=True):
        assert n_taps > 0
        self.n_samples  = n_samples
        self.n_taps     = n_taps
        self.data_width = data_width
        self.sink   = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source = stream.Endpoint(iq_layout(data_width, n_samples))

        # # #

        self.coeffs = LiteDSPFIRCoefficients(n_taps=n_taps, data_width=data_width,
            coefficients=coefficients, with_csr=with_csr)
        self.fir_i  = LiteDSPParallelFIRFilter(n_samples=n_samples, n_taps=n_taps, data_width=data_width,
            shift=shift)
        self.fir_q  = LiteDSPParallelFIRFilter(n_samples=n_samples, n_taps=n_taps, data_width=data_width,
            shift=shift)
        self.latency = self.fir_i.latency

        self.comb += [
            [self.fir_i.coeffs[t].eq(self.coeffs.values[t]) for t in range(n_taps)],
            [self.fir_q.coeffs[t].eq(self.coeffs.values[t]) for t in range(n_taps)],
            self.fir_i.sink.valid.eq(self.sink.valid),
            self.fir_q.sink.valid.eq(self.sink.valid),
            self.fir_i.sink.data.eq(self.sink.i),
            self.fir_q.sink.data.eq(self.sink.q),
            self.sink.ready.eq(self.fir_i.sink.ready & self.fir_q.sink.ready),
            self.source.valid.eq(self.fir_i.source.valid & self.fir_q.source.valid),
            self.source.i.eq(self.fir_i.source.data),
            self.source.q.eq(self.fir_q.source.data),
            self.fir_i.source.ready.eq(self.source.ready),
            self.fir_q.source.ready.eq(self.source.ready),
        ]
