#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Hamming (2^m - 1, 2^m - 1 - m) encoder / decoder on bit streams, optional SECDED parity."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common      import check, bits_for
from litedsp.comm.design import hamming_columns, hamming_params

# Hamming Encoder ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPHammingEncoder(LiteXModule):
    """Systematic Hamming encoder on a bit stream: ``k`` message bits in, the ``n = 2^m - 1``
    codeword bits out (message first, then the ``m`` parity bits; with ``secded`` an overall
    parity bit follows, ``n + 1``). Framed (``first`` on the first codeword bit, ``last`` on the
    last); ``cycles_per_block = n (+1) + 1``. ``latency = None``."""
    def __init__(self, m=3, secded=False, with_csr=True):
        check(3 <= m <= 6, "expected 3 <= m <= 6")
        self.m, self.secded = m, secded
        self.n, self.k = hamming_params(m, secded)
        self.latency = None
        self.cycles_per_block = self.n + 1
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.blocks = Signal(32)

        # # #

        m_, k, cols = m, self.k, hamming_columns(m)
        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        idx = Signal(max=self.n + 1)
        par = Signal(m_)
        q   = Signal()                                                  # Overall parity.
        col = Signal(m_)
        self.comb += col.eq(Array([C(c, m_) for c in cols[:k]])[idx])
        out_bit = Signal()
        emit = Signal()
        self.fsm = fsm = FSM(reset_state="MESSAGE")
        fsm.act("MESSAGE",
            self.sink.ready.eq(adv),
            emit.eq(self.sink.valid),
            out_bit.eq(self.sink.data),
            If(self.sink.valid & adv,
                NextValue(par, par ^ Mux(self.sink.data, col, 0)),
                NextValue(q, q ^ self.sink.data),
                If(idx == k - 1, NextValue(idx, 0), NextState("PARITY")).Else(
                    NextValue(idx, idx + 1)),
            ),
        )
        pbit = Signal()
        self.comb += pbit.eq(Array([par[i] for i in range(m_)])[idx[:bits_for(m_ - 1)]] if m_ > 1
                                                                              else par[0])
        fsm.act("PARITY",
            emit.eq(1),
            out_bit.eq(pbit),
            If(adv,
                NextValue(q, q ^ pbit),
                If(idx == m_ - 1,
                    NextValue(idx, 0),
                    If(secded, NextState("OVERALL")).Else(NextValue(par, 0), NextValue(q,
                        0), NextValue(self.blocks, self.blocks + 1), NextState("MESSAGE")),
                ).Else(
                    NextValue(idx, idx + 1),
                ),
            ),
        )
        fsm.act("OVERALL",
            emit.eq(1),
            out_bit.eq(q),
            If(adv, NextValue(par, 0), NextValue(q, 0), NextValue(self.blocks, self.blocks + 1),
               NextState("MESSAGE")),
        )
        self.sync += If(adv,
            self.source.valid.eq(emit),
            self.source.data.eq(out_bit),
            self.source.first.eq(fsm.ongoing("MESSAGE") & (idx == 0)),
            self.source.last.eq(fsm.ongoing("OVERALL") if secded
                                            else (fsm.ongoing("PARITY") & (idx == m_ - 1))),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=8, offset=0, description="Codeword bits."),
            CSRField("k", size=8, offset=8, description="Message bits."),
            CSRField("secded", size=1, offset=16, description="Overall parity bit present."),
        ])
        self._blocks = CSRStatus(32, name="blocks", description="Codewords sent.")
        self.comb += [self._config.fields.n.eq(self.n), self._config.fields.k.eq(self.k),
                      self._config.fields.secded.eq(int(self.secded)),
                      self._blocks.status.eq(self.blocks)]

# Hamming Decoder ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPHammingDecoder(LiteXModule):
    """Hamming decoder: ``n (+1)`` codeword bits in, ``k`` corrected message bits out (framed).

    RECEIVE accumulates the syndrome (XOR of the parity columns of the received ones) and the
    overall parity; DECIDE flips the bit whose column equals the syndrome (single error) or,
    with ``secded``, flags a double error (syndrome non-zero with even overall parity) and passes
    the message through uncorrected (``uncorrectable``, counted). Status: ``corrected`` (last
    block), ``corrected_total``, ``uncorrectable`` sticky, ``uncorrectable_count``, ``clear``.
    ``cycles_per_block = n (+1) + 1 + k``; ``latency = None``."""
    def __init__(self, m=3, secded=False, with_csr=True):
        check(3 <= m <= 6, "expected 3 <= m <= 6")
        self.m, self.secded = m, secded
        self.n, self.k = hamming_params(m, secded)
        self.latency = None
        self.cycles_per_block = self.n + 1 + self.k
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.corrected           = Signal()
        self.corrected_total     = Signal(32)
        self.uncorrectable       = Signal()
        self.uncorrectable_count = Signal(32)
        self.blocks = Signal(32)
        self.clear  = Signal()

        # # #

        m_, k, n = m, self.k, (1 << m) - 1                         # n: Hamming length (no overall).
        cols = hamming_columns(m)
        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        idx  = Signal(max=self.n + 1)
        bits = Signal(self.n)                                           # Received codeword.
        synd = Signal(m_)
        q    = Signal()
        col  = Signal(m_)
        self.comb += col.eq(Array([C(c, m_) for c in cols] + ([C(0, m_)] if secded else []))[idx])
        flip = Signal(n)                                                # One-hot correction mask.
        for i, c in enumerate(cols):
            self.comb += flip[i].eq(synd == c)
        double = Signal()
        self.comb += double.eq(int(secded) & (synd != 0) & ~q)
        self.fsm = fsm = FSM(reset_state="RECEIVE")
        fsm.act("RECEIVE",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                # Bit i lands at position i after n(+1) shifts.
                NextValue(bits, Cat(bits[1:], self.sink.data)),
                NextValue(synd, synd ^ Mux(self.sink.data, col, 0)),
                NextValue(q, q ^ self.sink.data),
                If(idx == self.n - 1, NextValue(idx, 0), NextState("DECIDE")).Else(
                    NextValue(idx, idx + 1)),
            ),
        )
        fixed = Signal(n)
        self.comb += fixed.eq(bits[:n] ^ Mux(double, 0, flip))
        msg = Signal(k)
        fsm.act("DECIDE",
            NextValue(msg, fixed[:k]),
            NextValue(self.corrected, (synd != 0) & ~double),
            If((synd != 0) & ~double, NextValue(self.corrected_total, self.corrected_total + 1)),
            If(double, NextValue(self.uncorrectable, 1),
               NextValue(self.uncorrectable_count, self.uncorrectable_count + 1)),
            NextValue(self.blocks, self.blocks + 1),
            NextValue(synd, 0), NextValue(q, 0), NextValue(idx, 0),
            NextState("OUT"),
        )
        emit = Signal()
        fsm.act("OUT",
            emit.eq(1),
            If(adv,
                If(idx == k - 1, NextValue(idx, 0), NextState("RECEIVE")).Else(
                    NextValue(idx, idx + 1)),
            ),
        )
        self.sync += [
            If(adv,
                self.source.valid.eq(emit),
                self.source.data.eq(Array([msg[i] for i in range(k)])[idx[:bits_for(k - 1)]]),
                self.source.first.eq(emit & (idx == 0)),
                self.source.last.eq(emit & (idx == k - 1)),
            ),
            If(self.clear, self.uncorrectable.eq(0)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=8, offset=0, description="Codeword bits."),
            CSRField("k", size=8, offset=8, description="Message bits."),
            CSRField("secded", size=1, offset=16, description="Double-error detection."),
        ])
        self._control = CSRStorage(fields=[CSRField("clear", size=1, offset=0, pulse=True, description="Clear the uncorrectable flag.")])
        self._status  = CSRStatus(fields=[
            CSRField("corrected",     size=1, offset=0, description="The last block was corrected."),
            CSRField("uncorrectable", size=1, offset=1, description="Sticky: a double error was detected."),
        ])
        self._corrected_total     = CSRStatus(32, name="corrected_total",
                                              description="Blocks corrected since reset.")
        self._uncorrectable_count = CSRStatus(32, name="uncorrectable_count",
                                              description="Double errors since reset.")
        self._blocks = CSRStatus(32, name="blocks", description="Blocks decoded.")
        self.comb += [
            self._config.fields.n.eq(self.n), self._config.fields.k.eq(self.k),
            self._config.fields.secded.eq(int(self.secded)),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.corrected.eq(self.corrected),
            self._status.fields.uncorrectable.eq(self.uncorrectable),
            self._corrected_total.status.eq(self.corrected_total),
            self._uncorrectable_count.status.eq(self.uncorrectable_count),
            self._blocks.status.eq(self.blocks),
        ]
