#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Hard-decision Viterbi decoder for the rate-1/n convolutional encoder.

Decodes the output of :class:`~litedsp.comm.coding.LiteDSPConvEncoder` (same ``constraint``/``polys``
conventions: symbol bit ``k`` is the parity for ``polys[k]``). Fully-parallel add-compare-select
over the ``2**(K-1)`` states with register-exchange survivor paths of depth ``traceback``
(default ``8*K``, well past the ~5K convergence rule of thumb), path metrics normalized by the
global minimum each step. One decoded bit per input symbol; the first ``traceback`` symbols are
absorbed to converge, after which the output stream is bit-aligned to the encoder input.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

# Helpers ------------------------------------------------------------------------------------------

def _parity_int(v):
    p = 0
    while v:
        p ^= v & 1
        v >>= 1
    return p

def _transitions(constraint, polys):
    """Per-state predecessor table: ``preds[s] = [(p, expected_symbol), ...]``.

    A transition from state ``p`` with input bit ``b`` goes to ``s = (b | p << 1) & mask`` and
    emits symbol bits ``parity(poly & (b | p << 1))`` — mirroring ConvEncoder's shift register.
    """
    n_states = 1 << (constraint - 1)
    mask     = n_states - 1
    preds    = [[] for _ in range(n_states)]
    for p in range(n_states):
        for b in (0, 1):
            full = b | (p << 1)
            sym  = 0
            for k, g in enumerate(polys):
                sym |= _parity_int(g & full) << k
            preds[full & mask].append((p, sym))
    return preds

def _min_tree(pairs, comb):
    """Reduce [(metric, payload)] to the minimum-metric element (ties keep the earlier one)."""
    while len(pairs) > 1:
        nxt = []
        for k in range(0, len(pairs) - 1, 2):
            (m0, p0), (m1, p1) = pairs[k], pairs[k + 1]
            m = Signal(len(m0))
            p = Signal(len(p0))
            comb += If(m1 < m0, m.eq(m1), p.eq(p1)).Else(m.eq(m0), p.eq(p0))
            nxt.append((m, p))
        if len(pairs) % 2:
            nxt.append(pairs[-1])
        pairs = nxt
    return pairs[0]

# Viterbi Decoder ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPViterbiDecoder(LiteXModule):
    """Hard-decision Viterbi decoder (rate 1/n, register-exchange survivors)."""
    def __init__(self, constraint=7, polys=(0o171, 0o133), traceback=None, metric_width=10,
        with_csr=True):
        n_states  = 1 << (constraint - 1)
        n_bits    = len(polys)
        traceback = traceback or 8*constraint
        self.constraint = constraint
        self.polys      = polys
        self.traceback  = traceback
        self.latency    = 1
        self.sink   = stream.Endpoint([("data", n_bits)])
        self.source = stream.Endpoint([("data", 1)])

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Path metrics (state 0 favored at reset: the encoder starts zeroed) + survivors.
        big     = 1 << (metric_width - 2)
        metrics = [Signal(metric_width, reset=(0 if s == 0 else big)) for s in range(n_states)]
        survs   = [Signal(traceback) for s in range(n_states)]

        # Hamming branch metrics for every possible expected symbol value.
        bm = {}
        for sym in range(1 << n_bits):
            s = Signal(max=n_bits + 1)
            self.comb += s.eq(sum((self.sink.data ^ sym)[k] for k in range(n_bits)))
            bm[sym] = s

        # ACS: per-state add-compare-select (ties keep predecessor 0).
        preds    = _transitions(constraint, polys)
        new_ms   = []
        new_ss   = []
        for s in range(n_states):
            (p0, e0), (p1, e1) = preds[s]
            m0 = Signal(metric_width + 1)
            m1 = Signal(metric_width + 1)
            self.comb += [m0.eq(metrics[p0] + bm[e0]), m1.eq(metrics[p1] + bm[e1])]
            m  = Signal(metric_width + 1)
            sv = Signal(traceback)
            self.comb += If(m1 < m0,
                m.eq(m1), sv.eq(Cat(C(s & 1, 1), survs[p1][:-1])),
            ).Else(
                m.eq(m0), sv.eq(Cat(C(s & 1, 1), survs[p0][:-1])),
            )
            new_ms.append(m)
            new_ss.append(sv)

        # Normalize by the global minimum (also selects the best survivor for the output).
        best_m, best_sv = _min_tree([(new_ms[s], new_ss[s]) for s in range(n_states)], self.comb)
        self.sync += If(xfer, *[metrics[s].eq(new_ms[s] - best_m) for s in range(n_states)],
                              *[survs[s].eq(new_ss[s]) for s in range(n_states)])

        # Output: the oldest bit of the best path, once the exchange registers are full (the
        # bit for input 0 reaches the survivor MSB on the traceback-th consumed symbol).
        warmup = Signal(max=traceback + 1, reset=traceback - 1)
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid & (warmup == 0)),
            self.source.data.eq(best_sv[-1]),
            If(xfer & (warmup != 0), warmup.eq(warmup - 1)),
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("constraint", size=8,  description="Constraint length K."),
            CSRField("traceback",  size=16, description="Survivor depth (decoding delay)."),
        ])
        self.comb += [
            self._config.fields.constraint.eq(self.constraint),
            self._config.fields.traceback.eq(self.traceback),
        ]
