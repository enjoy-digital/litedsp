#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import real_layout, iq_layout, scaled

# Helpers ------------------------------------------------------------------------------------------

def _adder_tree(terms):
    """Balanced combinational adder tree over a list of Migen expressions."""
    while len(terms) > 1:
        terms = [terms[i] + terms[i+1] for i in range(0, len(terms)-1, 2)] + \
                ([terms[-1]] if (len(terms) % 2) else [])
    return terms[0]

# FIR Coefficients ---------------------------------------------------------------------------------

class LiteDSPFIRCoefficients(LiteXModule):
    """Holds the ``n_taps`` FIR coefficients, with an optional per-tap CSR interface.

    Coefficients are signed Qm.n (same width as samples). The default is a unit impulse
    (tap 0 = 1.0), i.e. a transparent filter; pass ``coefficients`` to preload a real filter.
    """
    def __init__(self, n_taps=32, data_width=16, coefficients=None, with_csr=True):
        self.n_taps     = n_taps
        self.data_width = data_width
        self.values     = Array([Signal((data_width, True)) for _ in range(n_taps)])

        if coefficients is None:
            coefficients = [(1 << (data_width-1)) - 1] + [0]*(n_taps-1)  # Unit impulse.
        assert len(coefficients) == n_taps
        self.coefficients = coefficients

        if with_csr:
            self.add_csr()
        else:
            for i in range(n_taps):
                self.values[i].reset = coefficients[i]

    def add_csr(self):
        for i in range(self.n_taps):
            csr = CSRStorage(self.data_width, reset=self.coefficients[i], name=f"coeff_{i}",
                description=f"FIR coefficient {i} (signed Qm.n).")
            self.add_module(name=f"coeff_{i}", module=csr)
            self.comb += self.values[i].eq(csr.storage)

# FIR Filter (real) --------------------------------------------------------------------------------

class LiteDSPFIRFilter(LiteXModule):
    """Pipelined single-rate real FIR filter with stream I/O and round+saturate output.

    Computes ``y[k] = sum_t coeffs[t] * x[k-t]`` with a fixed 3-cycle latency. With
    ``symmetric=True`` the (linear-phase) filter folds tap pairs to halve the multiplier
    count; the caller must provide symmetric coefficients.

    Backpressure is handled with an elastic pipeline: the sample shift-register advances only
    on real input transfers (so bubbles never enter the convolution history), while the
    arithmetic stages and the valid pipeline drain on every accepted output beat.
    """
    def __init__(self, n_taps=32, data_width=16, symmetric=False, shift=None):
        assert n_taps > 0
        if shift is None:
            shift = data_width - 1
        self.n_taps     = n_taps
        self.data_width = data_width
        self.latency    = 3
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(real_layout(data_width))
        self.coeffs = Array([Signal((data_width, True)) for _ in range(n_taps)])

        # # #

        # Handshake: drain when output can accept; consume an input on each drained beat.
        # ------------------------------------------------------------------------------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A real input sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            xfer.eq(self.sink.valid & adv),
            self.sink.ready.eq(adv),
        ]

        # Sample shift register (advances only on real transfers; regs[0] = newest).
        # -------------------------------------------------------------------------
        regs = [Signal((data_width, True)) for _ in range(n_taps)]
        self.sync += If(xfer, regs[0].eq(self.sink.data))
        for t in range(1, n_taps):
            self.sync += If(xfer, regs[t].eq(regs[t-1]))

        # (Optional fold) + multiply, registered on drain.
        # ------------------------------------------------
        if symmetric:
            n_prod    = (n_taps + 1)//2
            prod_bits = 2*data_width + 1   # (data_width+1) pre-add * data_width.
        else:
            n_prod    = n_taps
            prod_bits = 2*data_width
        prods = [Signal((prod_bits, True)) for _ in range(n_prod)]
        for t in range(n_prod):
            if symmetric:
                j   = n_taps - 1 - t
                tap = regs[t] if (j == t) else (regs[t] + regs[j])  # Fold mirrored taps.
            else:
                tap = regs[t]
            self.sync += If(adv, prods[t].eq(tap * self.coeffs[t]))

        # Adder tree (combinational) + rescale (round + saturate), registered on drain.
        # -----------------------------------------------------------------------------
        acc_bits = prod_bits + int(math.ceil(math.log2(n_prod))) + 1
        acc      = Signal((acc_bits, True))
        self.comb += acc.eq(_adder_tree(list(prods)))
        result, _ = scaled(acc, shift, data_width)
        out = Signal((data_width, True))
        self.sync += If(adv, out.eq(result))
        self.comb += self.source.data.eq(out)

        # Valid pipeline (matches the 3 register stages, drains on each beat).
        # -------------------------------------------------------------------
        valid_pipe = Signal(self.latency)
        self.sync += If(adv, valid_pipe.eq(Cat(self.sink.valid, valid_pipe[:-1])))
        self.comb += self.source.valid.eq(valid_pipe[-1])

# FIR Filter (complex) -----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPFIRFilterComplex(LiteXModule):
    """Complex FIR: identical real FIRs on I and Q, shared coefficients, with bypass + CSR."""
    def __init__(self, n_taps=32, data_width=16, symmetric=False, coefficients=None,
        shift=None, with_csr=True):
        assert n_taps > 0
        self.n_taps     = n_taps
        self.data_width = data_width
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.bypass = Signal()

        # # #

        self.coeffs = LiteDSPFIRCoefficients(n_taps=n_taps, data_width=data_width,
            coefficients=coefficients, with_csr=with_csr)
        self.fir_i  = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width, symmetric=symmetric, shift=shift)
        self.fir_q  = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width, symmetric=symmetric, shift=shift)
        self.latency = self.fir_i.latency

        self.comb += [
            [self.fir_i.coeffs[i].eq(self.coeffs.values[i]) for i in range(n_taps)],
            [self.fir_q.coeffs[i].eq(self.coeffs.values[i]) for i in range(n_taps)],
        ]
        self.comb += If(self.bypass,
            self.sink.connect(self.source),
            self.fir_i.sink.valid.eq(0),
            self.fir_q.sink.valid.eq(0),
        ).Else(
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
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._bypass = CSRStorage(1, reset=0, name="bypass", description="Bypass filter (passthrough).")
        self.comb += self.bypass.eq(self._bypass.storage)
