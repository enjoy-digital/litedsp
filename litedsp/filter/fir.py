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

from litedsp.common import check, real_layout, iq_layout, scaled, add_bypass

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
        check(len(coefficients) == n_taps, "expected len(coefficients) == n_taps")
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

class LiteDSPFIRCoefficientsPort(LiteXModule):
    """``n_taps`` coefficient registers behind an index/value CSR load port.

    Same ``values`` Array and unit-impulse default as :class:`LiteDSPFIRCoefficients`, but with
    two CSRs instead of one per tap: for large banks (e.g. 63 taps x several filters) the
    per-tap CSR bank can make the bus write decode the design's critical path and bloats the
    register map. ``index`` auto-increments on each ``value`` write, so loading a filter is:
    write ``index = 0``, then stream the taps in order.
    """
    def __init__(self, n_taps=32, data_width=16, coefficients=None, with_csr=True):
        self.n_taps     = n_taps
        self.data_width = data_width
        self.values     = Array([Signal((data_width, True)) for _ in range(n_taps)])

        if coefficients is None:
            coefficients = [(1 << (data_width-1)) - 1] + [0]*(n_taps-1)  # Unit impulse.
        check(len(coefficients) == n_taps, "expected len(coefficients) == n_taps")
        for i in range(n_taps):
            self.values[i].reset = coefficients[i]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._index = CSRStorage(bits_for(self.n_taps - 1),
            description="Coefficient index; auto-increments on each value write.")
        self._value = CSRStorage(self.data_width,
            description="Write the indexed FIR coefficient (signed Qm.n).")
        index = Signal(bits_for(self.n_taps - 1))
        self.sync += [
            If(self._index.re,
                index.eq(self._index.storage),
            ),
            If(self._value.re,
                self.values[index].eq(self._value.storage),
                index.eq(index + 1),
            ),
        ]

# FIR Filter (real) --------------------------------------------------------------------------------

class LiteDSPFIRFilter(LiteXModule):
    """Pipelined single-rate real FIR filter with stream I/O and round+saturate output.

    Computes ``y[k] = sum_t coeffs[t] * x[k-t]``. With
    ``symmetric=True`` the (linear-phase) filter folds tap pairs to halve the multiplier
    count; the caller must provide symmetric coefficients.

    Backpressure is handled with an elastic pipeline: the sample shift-register advances only
    on real input transfers (so bubbles never enter the convolution history), while the
    arithmetic stages and the valid pipeline drain on every accepted output beat.

    Parameters
    ----------
    symmetric : bool
        Fold mirrored tap pairs before the multiply, halving the multiplier count (DSP blocks)
        for linear-phase filters. The provided coefficients must actually be symmetric.
    architecture : str
        ``"classic"`` uses a combinational balanced reduction after the product registers and
        has three clocks of latency. ``"pipelined"`` registers every adder-tree level, retaining
        one-sample-per-clock throughput while adding ``ceil(log2(n_products))`` clocks.
        ``"mac"`` computes the convolution serially with ``n_macs`` multiply-accumulate units
        (~``n_macs`` DSP blocks instead of ``n_taps``): a fully pipelined operand-mux ->
        product -> accumulate -> pairwise-sum-tree scan taking ``cycles_per_sample`` clocks per
        input. Intended for decimated streams where a new sample arrives at most every
        ``cycles_per_sample`` clocks (e.g. after a CIC) -- input arriving faster is
        backpressured. Sample-exact vs "classic".
    n_macs : int
        Multiply-accumulate units for the ``"mac"`` architecture (ignored otherwise).
    """
    def __init__(self, n_taps=32, data_width=16, symmetric=False, shift=None,
        architecture="classic", n_macs=4):
        check(n_taps > 0, "expected n_taps > 0")
        check(architecture in ("classic", "pipelined", "mac"),
            "architecture must be 'classic', 'pipelined' or 'mac'.")
        if shift is None:
            shift = data_width - 1
        self.n_taps     = n_taps
        self.data_width = data_width
        self.architecture = architecture
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(real_layout(data_width))
        self.coeffs = Array([Signal((data_width, True)) for _ in range(n_taps)])

        # # #

        if architecture == "mac":
            check(not symmetric, "the 'mac' architecture does not support symmetric folding")
            check(n_macs > 0, "expected n_macs > 0")
            self._build_mac(n_taps, data_width, shift, n_macs)
            return

        # Handshake: drain when output can accept; consume an input on each drained beat.
        # -------------------------------------------------------------------------------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A real input sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            xfer.eq(self.sink.valid & adv),
            self.sink.ready.eq(adv),
        ]

        # Sample shift register (advances only on real transfers; regs[0] = newest).
        # --------------------------------------------------------------------------
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

        # Adder tree + rescale (round + saturate), registered on drain.
        # ----------------------------------------------------------------
        acc_bits = prod_bits + int(math.ceil(math.log2(n_prod))) + 1
        if architecture == "classic":
            acc = Signal((acc_bits, True))
            self.comb += acc.eq(_adder_tree(list(prods)))
            tree_levels = 0
        else:
            # Materialize the balanced tree one registered level at a time. Keeping every
            # intermediate at the final accumulator width preserves the classic full-precision
            # arithmetic while preventing Vivado from flattening a runtime-coefficient FIR into
            # one long DSP48 cascade.
            tree = list(prods)
            tree_levels = 0
            while len(tree) > 1:
                next_tree = [Signal((acc_bits, True)) for _ in range((len(tree) + 1)//2)]
                assignments = []
                for i, node in enumerate(next_tree):
                    lo = 2*i
                    assignments.append(node.eq(tree[lo] + tree[lo + 1]
                        if lo + 1 < len(tree) else tree[lo]))
                self.sync += If(adv, *assignments)
                tree = next_tree
                tree_levels += 1
            acc = tree[0]
        self.latency = 3 + tree_levels
        result, _ = scaled(acc, shift, data_width)
        out = Signal((data_width, True))
        self.sync += If(adv, out.eq(result))
        self.comb += self.source.data.eq(out)

        # Valid pipeline (matches the 3 register stages, drains on each beat).
        # --------------------------------------------------------------------
        valid_pipe = Signal(self.latency)
        self.sync += If(adv, valid_pipe.eq(Cat(self.sink.valid, valid_pipe[:-1])))
        self.comb += self.source.valid.eq(valid_pipe[-1])

        # Bypass.
        # -------
        add_bypass(self, output_registered=False)  # Output is comb-driven from the last stage.

    def _build_mac(self, n_taps, data_width, shift, n_macs):
        """Serial MAC datapath: accept one sample, scan the taps in ``ceil(n_taps/n_macs)``
        cycles (each MAC owns a contiguous chunk), pairwise-sum the partials one registered
        level per cycle, rescale, present. ``self.bypass`` passes samples through unfiltered
        (2 cycles/sample). Proven on hardware (Zynq 7020, 125 MHz)."""
        self.n_macs = n_macs
        self.chunk  = chunk = (n_taps + n_macs - 1)//n_macs
        levels      = (n_macs - 1).bit_length()          # Pairwise sum-tree depth.
        k_end       = chunk + 2 + levels                 # mux -> product -> accumulate -> tree.
        self.cycles_per_sample = k_end + 2               # + accept and present cycles.
        self.bypass = Signal()

        # Sample history: regs[t] = x[k-t] (advances only on accepted inputs).
        regs = [Signal((data_width, True)) for _ in range(n_taps)]
        self.sync += If(self.sink.valid & self.sink.ready,
            regs[0].eq(self.sink.data),
            *[regs[t].eq(regs[t-1]) for t in range(1, n_taps)],
        )

        # Zero-padded views so every MAC scans a full fixed-size chunk.
        n_pad    = chunk*n_macs
        zero     = Signal((data_width, True))
        regs_arr = Array(regs              + [zero]*(n_pad - n_taps))
        coef_arr = Array(list(self.coeffs) + [zero]*(n_pad - n_taps))

        acc_bits = 2*data_width + int(math.ceil(math.log2(n_taps))) + 1
        k    = Signal(max=k_end + 1)
        accs = [Signal((acc_bits, True)) for _ in range(n_macs)]

        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                NextValue(k, 0),
                *[NextValue(acc, 0) for acc in accs],
                If(self.bypass,
                    NextState("OUT"),
                ).Else(
                    NextState("MAC"),
                ),
            ),
        )
        # Pipelined MAC scan (operand mux, DSP-mapped product, accumulate each get a cycle).
        for m, acc in enumerate(accs):
            mux_d = Signal((data_width, True))
            mux_c = Signal((data_width, True))
            prod  = Signal((2*data_width, True))
            self.sync += If(fsm.ongoing("MAC"),
                If(k < chunk,
                    mux_d.eq(regs_arr[m*chunk + k]),
                    mux_c.eq(coef_arr[m*chunk + k]),
                ),
                If((k >= 1) & (k <= chunk),
                    prod.eq(mux_d * mux_c),
                ),
                If((k >= 2) & (k <= chunk + 1),
                    acc.eq(acc + prod),
                ),
            )
        fsm.act("MAC",
            If(k == k_end,
                NextState("OUT"),
            ).Else(
                NextValue(k, k + 1),
            ),
        )

        # Pairwise partial-sum tree, one registered level per cycle, then rescale.
        cur   = list(accs)
        width = acc_bits
        level = 0
        while len(cur) > 1:
            nxt = []
            for i in range(0, len(cur), 2):
                node = Signal((width + 1, True))
                expr = cur[i] if (i + 1 == len(cur)) else (cur[i] + cur[i+1])
                self.sync += If(fsm.ongoing("MAC") & (k == chunk + 2 + level), node.eq(expr))
                nxt.append(node)
            cur    = nxt
            width += 1
            level += 1
        result, _ = scaled(cur[0], shift, data_width)
        out = Signal((data_width, True))
        self.sync += [
            If(fsm.ongoing("MAC") & (k == k_end), out.eq(result)),
            If(fsm.ongoing("IDLE") & self.sink.valid & self.bypass, out.eq(self.sink.data)),
        ]

        fsm.act("OUT",
            self.source.valid.eq(1),
            If(self.source.ready,
                NextState("IDLE"),
            ),
        )
        self.comb += self.source.data.eq(out)

# FIR Filter (complex) -----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPFIRFilterComplex(LiteXModule):
    """Complex FIR: identical real FIRs on I and Q, shared coefficients, with bypass + CSR.

    Parameters
    ----------
    symmetric : bool
        Fold mirrored tap pairs in both the I and Q FIRs, halving the multiplier count (DSP
        blocks) for linear-phase filters; the coefficients must actually be symmetric.
    architecture : str
        ``"classic"`` uses the three-clock combinational-reduction filters. ``"pipelined"``
        registers every adder-tree level while retaining one complex sample per clock.
    """
    def __init__(self, n_taps=32, data_width=16, symmetric=False, coefficients=None,
        shift=None, with_csr=True, architecture="classic", n_macs=4):
        check(n_taps > 0, "expected n_taps > 0")
        self.n_taps     = n_taps
        self.data_width = data_width
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.bypass = Signal()

        # # #

        self.coeffs = LiteDSPFIRCoefficients(n_taps=n_taps, data_width=data_width,
            coefficients=coefficients, with_csr=with_csr)
        self.fir_i  = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width,
            symmetric=symmetric, shift=shift, architecture=architecture, n_macs=n_macs)
        self.fir_q  = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width,
            symmetric=symmetric, shift=shift, architecture=architecture, n_macs=n_macs)
        self.latency = getattr(self.fir_i, "latency", None)

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
