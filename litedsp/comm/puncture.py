#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Convolutional-code puncturing / depuncturing (rate adaptation around the rate-1/n mother code).

A puncturing matrix has one row per coded stream (row ``j`` for ``polys[j]``) and one column
per pattern period position: entry 1 keeps the bit, 0 drops it. The puncturer serializes the
kept bits of each symbol (column order, row 0 first); the depuncturer reassembles full symbols
for the soft Viterbi decoder, reinserting an erasure (LLR 0, free for both bit hypotheses)
at every dropped position.

The provided constants are the DVB-S matrices (ETSI EN 300 421, X = G1 = 0o171 on row 0,
Y = G2 = 0o133 on row 1), also used by DVB-T; other standards (e.g. 802.11a's 2/3 and 3/4)
use column/row permutations of the same rates, which the ``pattern`` parameter expresses
directly:

    PUNCTURE_1_2 = [[1],             [1]]              X1 Y1
    PUNCTURE_2_3 = [[1, 0],          [1, 1]]           X1 Y1 Y2
    PUNCTURE_3_4 = [[1, 0, 1],       [1, 1, 0]]        X1 Y1 Y2 X3
    PUNCTURE_5_6 = [[1, 0, 1, 0, 1], [1, 1, 0, 1, 0]]  X1 Y1 Y2 X3 Y4 X5
    PUNCTURE_7_8 = [[1, 0, 0, 0, 1, 0, 1],
                    [1, 1, 1, 1, 0, 1, 0]]             X1 Y1 Y2 Y3 Y4 X5 Y6 X7
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check

# Puncturing Patterns (DVB-S / ETSI EN 300 421) ------------------------------------------------------

PUNCTURE_1_2 = [[1],                   [1]]
PUNCTURE_2_3 = [[1, 0],                [1, 1]]
PUNCTURE_3_4 = [[1, 0, 1],             [1, 1, 0]]
PUNCTURE_5_6 = [[1, 0, 1, 0, 1],       [1, 1, 0, 1, 0]]
PUNCTURE_7_8 = [[1, 0, 0, 0, 1, 0, 1], [1, 1, 1, 1, 0, 1, 0]]

# Helpers --------------------------------------------------------------------------------------------

def _kept(pattern, n):
    """Validate ``pattern`` and return per-column kept row indices ``[[j, ...], ...]``."""
    check(len(pattern) == n, f"expected pattern to have n = {n} rows")
    period = len(pattern[0])
    check(period >= 1, "expected a non-empty pattern")
    check(all(len(row) == period for row in pattern), "expected equal-length pattern rows")
    check(all(bit in (0, 1) for row in pattern for bit in row), "expected 0/1 pattern entries")
    kept = [[j for j in range(n) if pattern[j][t]] for t in range(period)]
    check(all(kept), "expected every pattern column to keep at least one bit")
    return kept

# Puncturer ------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPuncturer(LiteXModule):
    """TX puncturer: drops coded bits of the rate-1/n stream per the puncturing matrix.

    One n-bit coded symbol in (:class:`~litedsp.comm.coding.LiteDSPConvEncoder` output), the
    kept bits out serially (one bit per beat, row 0 first) — pattern column ``t mod period``
    applies to input symbol ``t``. Variable rate (``latency = None``): a symbol takes as many
    output beats as its column keeps. ``phase_rst`` (CSR pulse) re-zeros the pattern phase for
    subsequently accepted symbols (block-boundary alignment).

    Parameters
    ----------
    pattern : list
        Puncturing matrix as ``n`` lists of 0/1 (row ``j`` for coded stream ``polys[j]``,
        one column per period position; see the module-level DVB-S constants). Every column
        must keep at least one bit. Default: ``PUNCTURE_1_2`` (no puncturing).
    n : int
        Coded bits per input symbol (the mother code's 1/n rate; sink data width).
    """
    def __init__(self, pattern=None, n=2, with_csr=True):
        pattern = PUNCTURE_1_2 if pattern is None else pattern
        check(n >= 2, "expected n >= 2 (rate-1/n mother code)")
        kept   = _kept(pattern, n)
        period = len(kept)
        counts = [len(k) for k in kept]
        self.pattern = pattern
        self.n       = n
        self.latency = None  # Variable rate: 1..n output beats per input symbol.
        self.sink   = stream.Endpoint([("data", n)])
        self.source = stream.Endpoint([("data", 1)])
        self.phase_rst = Signal()  # Re-zero the pattern phase (next accepted symbol).

        # # #

        # State: held symbol being serialized + pattern phase of the next symbol.
        # -----------------------------------------------------------------------
        busy  = Signal()                # A symbol's kept bits are being emitted.
        sym   = Signal(n)               # Held coded symbol.
        cur   = Signal(max=max(period, 2))  # Pattern column of the held symbol.
        idx   = Signal(max=max(n, 2))       # Position in the column's kept-bit list.
        phase   = Signal(max=max(period, 2))  # Pattern column of the next accepted symbol.
        out_bit = Signal()                  # Held kept bit; avoids a live symbol/phase mux.
        last    = Signal()                  # Emitting the held symbol's last kept bit.
        xfer    = Signal()                  # Input symbol accepted this cycle.
        self.comb += [
            last.eq(idx == Array([c - 1 for c in counts])[cur]),
            self.sink.ready.eq(~busy | (self.source.ready & last)),
            xfer.eq(self.sink.valid & self.sink.ready),
            self.source.valid.eq(busy),
            self.source.data.eq(out_bit),
        ]

        # Capture the first kept bit with each symbol, then advance the held bit only when the
        # preceding beat transfers.  The first valid beat remains one cycle after acceptance;
        # the active output path no longer includes a symbol/column/index decode.
        first_cases = {t: out_bit.eq(self.sink.data[rows[0]]) for t, rows in enumerate(kept)}
        advance_cases = {
            t: Case(idx, {i: out_bit.eq(sym[rows[i + 1]]) for i in range(len(rows) - 1)})
            for t, rows in enumerate(kept) if len(rows) > 1
        }
        advance_stmts = [Case(cur, advance_cases)] if advance_cases else []

        # Serialization / phase advance (phase_rst wins over a concurrent accept).
        # ------------------------------------------------------------------------
        self.sync += [
            If(self.source.valid & self.source.ready,
                If(last, busy.eq(0)).Else(
                    idx.eq(idx + 1),
                    *advance_stmts,
                ),
            ),
            If(xfer,
                busy.eq(1),
                sym.eq(self.sink.data),
                cur.eq(phase),
                idx.eq(0),
                Case(phase, first_cases),
                If(phase == period - 1, phase.eq(0)).Else(phase.eq(phase + 1)),
            ),
            If(self.phase_rst, phase.eq(0)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("phase_rst", size=1, offset=0, pulse=True,
                description="Re-zero the puncturing pattern phase (applies to the next accepted symbol)."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("period", size=8, description="Puncturing pattern period (columns)."),
            CSRField("n",      size=8, description="Coded bits per input symbol (mother code 1/n)."),
        ])
        self.comb += [
            self.phase_rst.eq(self._control.fields.phase_rst),
            self._config.fields.period.eq(len(self.pattern[0])),
            self._config.fields.n.eq(self.n),
        ]

# Depuncturer ----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDepuncturer(LiteXModule):
    """RX depuncturer: reassembles full soft symbols, reinserting erasures (LLR 0) per pattern.

    One signed ``llr_bits`` LLR in per beat (the puncturer's serial kept-bit order, e.g. from
    the soft demapper), one packed n-slot LLR symbol out per pattern column — slot ``j`` at
    bits ``[j*llr_bits +: llr_bits]``, LLR 0 at punctured slots — feeding the soft
    :class:`~litedsp.comm.viterbi.LiteDSPViterbiDecoder` (``llr_bits`` set) directly.
    Variable rate (``latency = None``): a column consumes as many input beats as it keeps.
    ``phase_rst`` (CSR pulse) re-zeros the pattern phase and drops any partially assembled
    symbol (block-boundary alignment).

    Parameters
    ----------
    pattern : list
        Puncturing matrix, matching the transmitter's (see the module-level DVB-S
        constants). Every column must keep at least one bit. Default: ``PUNCTURE_1_2``.
    n : int
        Coded bits per output symbol (the mother code's 1/n rate).
    llr_bits : int
        Width of each signed LLR (matching the soft demapper/decoder).
    """
    def __init__(self, pattern=None, n=2, llr_bits=4, with_csr=True):
        pattern = PUNCTURE_1_2 if pattern is None else pattern
        check(n >= 2, "expected n >= 2 (rate-1/n mother code)")
        check(llr_bits >= 2, "expected llr_bits >= 2")
        kept   = _kept(pattern, n)
        period = len(kept)
        counts = [len(k) for k in kept]
        self.pattern  = pattern
        self.n        = n
        self.llr_bits = llr_bits
        self.latency  = None  # Variable rate: 1..n input beats per output symbol.
        self.sink   = stream.Endpoint([("llrs", llr_bits)])
        self.source = stream.Endpoint([("llrs", n*llr_bits)])
        self.phase_rst = Signal()  # Re-zero the pattern phase (drops a partial symbol).

        # # #

        # State: assembly slots for the current pattern column.
        # ------------------------------------------------------
        slots = [Signal(llr_bits, name=f"slot{j}") for j in range(n)]
        phase = Signal(max=max(period, 2))  # Pattern column being assembled.
        idx   = Signal(max=max(n, 2))       # Position in the column's kept-bit list.
        last  = Signal()                    # Current LLR completes the column.
        xfer  = Signal()                    # Input LLR accepted this cycle.
        self.comb += [
            last.eq(idx == Array([c - 1 for c in counts])[phase]),
            # Mid-symbol LLRs are absorbed freely; the completing one needs the output slot.
            self.sink.ready.eq(~last | self.source.ready | ~self.source.valid),
            xfer.eq(self.sink.valid & self.sink.ready),
        ]

        # Per-column slot capture and output assembly (erasure = 0 at punctured slots; the
        # completing LLR is routed straight into the output word).
        # ---------------------------------------------------------------------------------
        writes = []
        for t in range(period):
            for i, j in enumerate(kept[t][:-1]):
                writes.append(If((phase == t) & (idx == i), slots[j].eq(self.sink.llrs)))
        words = {}
        for t in range(period):
            parts = []
            for j in range(n):
                if pattern[j][t] == 0:
                    parts.append(C(0, llr_bits))         # Erasure.
                elif j == kept[t][-1]:
                    parts.append(self.sink.llrs)         # Arriving now.
                else:
                    parts.append(slots[j])               # Captured earlier.
            words[t] = Cat(*parts)
        self.sync += [
            If(self.source.ready, self.source.valid.eq(0)),
            If(xfer,
                *writes,
                If(last,
                    idx.eq(0),
                    If(phase == period - 1, phase.eq(0)).Else(phase.eq(phase + 1)),
                    self.source.valid.eq(1),
                    Case(phase, {t: self.source.llrs.eq(words[t]) for t in range(period)}),
                ).Else(idx.eq(idx + 1)),
            ),
            If(self.phase_rst, phase.eq(0), idx.eq(0)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("phase_rst", size=1, offset=0, pulse=True,
                description="Re-zero the pattern phase and drop any partially assembled symbol."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("period",   size=8, description="Puncturing pattern period (columns)."),
            CSRField("n",        size=8, description="Coded bits per output symbol (mother code 1/n)."),
            CSRField("llr_bits", size=8, description="Signed LLR width."),
        ])
        self.comb += [
            self.phase_rst.eq(self._control.fields.phase_rst),
            self._config.fields.period.eq(len(self.pattern[0])),
            self._config.fields.n.eq(self.n),
            self._config.fields.llr_bits.eq(self.llr_bits),
        ]
