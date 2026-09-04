#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Binary BCH encoder and decoder (bit-serial, narrow-sense codes over GF(2^m))."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common      import check, bits_for
from litedsp.comm.design import bch_generator, gf_tables, PRIMITIVE_POLYS

# GF helpers ---------------------------------------------------------------------------------------

def _gf_mul(module, a, b, m, poly):
    """Combinational GF(2^m) product (shift-and-add with reduction)."""
    r = Signal(m)
    acc = C(0, m)
    x   = a
    for i in range(m):
        acc = acc ^ Mux(b[i], x, 0)
        nx = Signal(m, name=f"gfx{i}")
        module.comb += nx.eq(Mux(x[m - 1], ((x << 1) & ((1 << m) - 1)) ^ (poly & ((1 << m) - 1)),
                                 (x << 1) & ((1 << m) - 1)))
        x = nx
    module.comb += r.eq(acc)
    return r

# BCH Encoder --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBCHEncoder(LiteXModule):
    """Systematic BCH(n, k) encoder on a bit stream: ``k`` message bits pass through while an
    LFSR divides by the generator ``g(x)``, then the ``n - k`` parity bits follow (MSB of the
    remainder first). Framed (``first`` / ``last`` per codeword); ``cycles_per_block = n + 1``;
    ``latency = None``."""
    def __init__(self, m=4, t=2, field_poly=None, with_csr=True):
        check(3 <= m <= 8 and 1 <= t <= 8, "expected 3 <= m <= 8 and 1 <= t <= 8")
        self.g, self.n, self.k = bch_generator(m, t, field_poly)
        self.m, self.t = m, t
        self.latency = None
        self.cycles_per_block = self.n + 1
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.blocks = Signal(32)

        # # #

        n, k, r = self.n, self.k, self.n - self.k
        gbits = [(self.g >> i) & 1 for i in range(r)]                   # g without the x^r term.
        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        idx = Signal(max=n + 1)
        lfsr = Signal(r)
        fb = Signal()
        self.comb += fb.eq(lfsr[r - 1] ^ self.sink.data)
        nxt = Signal(r)
        self.comb += nxt.eq(Cat(fb, *[lfsr[i - 1] ^ (fb if gbits[i] else 0) for i in range(1, r)])
            if r > 1 else fb)
        emit, out_bit = Signal(), Signal()
        self.fsm = fsm = FSM(reset_state="MESSAGE")
        fsm.act("MESSAGE",
            self.sink.ready.eq(adv), emit.eq(self.sink.valid), out_bit.eq(self.sink.data),
            If(self.sink.valid & adv,
                NextValue(lfsr, nxt),
                If(idx == k - 1, NextValue(idx, 0), NextState("PARITY")).Else(
                    NextValue(idx, idx + 1)),
            ),
        )
        fsm.act("PARITY",
            emit.eq(1), out_bit.eq(lfsr[r - 1]),
            If(adv,
                NextValue(lfsr, Cat(C(0, 1), lfsr[:r - 1]) if r > 1 else 0),
                If(idx == r - 1, NextValue(idx, 0), NextValue(self.blocks, self.blocks + 1),
                   NextState("MESSAGE")).Else(NextValue(idx, idx + 1)),
            ),
        )
        self.sync += If(adv,
            self.source.valid.eq(emit), self.source.data.eq(out_bit),
            self.source.first.eq(fsm.ongoing("MESSAGE") & (idx == 0)),
            self.source.last.eq(fsm.ongoing("PARITY") & (idx == r - 1)),
        )
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=8, offset=0, description="Codeword bits."),
            CSRField("k", size=8, offset=8, description="Message bits."),
            CSRField("t", size=4, offset=16, description="Correctable errors."),
        ])
        self._blocks = CSRStatus(32, name="blocks", description="Codewords sent.")
        self.comb += [self._config.fields.n.eq(self.n), self._config.fields.k.eq(self.k),
                      self._config.fields.t.eq(self.t),
                      self._blocks.status.eq(self.blocks)]

# BCH Decoder --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBCHDecoder(LiteXModule):
    """Bit-serial BCH(n, k) decoder: ``n`` codeword bits in, ``k`` corrected message bits out.

    RECEIVE evaluates the ``2t`` syndromes by Horner's rule (one GF multiply per syndrome per
    bit) and stores the codeword; BM runs the binary Berlekamp-Massey algorithm serially
    (``2t`` iterations of up to ``t + 1`` steps, one GF multiply / division per step through a
    small inverse ROM); CHIEN scans the ``n`` positions and flips the roots; OUT streams the ``k``
    corrected message bits. A locator degree above ``t`` or a root count below the degree
    flags ``uncorrectable`` (the block passes through uncorrected). Status: ``corrected`` (last
    block), ``corrected_total``, ``uncorrectable`` sticky, ``uncorrectable_count``, ``blocks``,
    ``clear``. ``cycles_per_block = n + 2 + 2t(t+2) + n + k + 2``; ``latency = None``."""
    def __init__(self, m=4, t=2, field_poly=None, with_csr=True):
        check(3 <= m <= 8 and 1 <= t <= 8, "expected 3 <= m <= 8 and 1 <= t <= 8")
        self.g, self.n, self.k = bch_generator(m, t, field_poly)
        self.m, self.t = m, t
        self.latency = None
        self.cycles_per_block = self.n + 2 + 2*t*(t + 2) + self.n + self.k + 2
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.corrected           = Signal()
        self.corrected_total     = Signal(32)
        self.uncorrectable       = Signal()
        self.uncorrectable_count = Signal(32)
        self.blocks = Signal(32)
        self.clear  = Signal()

        # # #

        n, k, m_, T = self.n, self.k, m, t
        poly = field_poly or PRIMITIVE_POLYS[m]
        exp, log = gf_tables(m, poly)
        N = (1 << m) - 1
        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        # Inverse ROM (index 0 unused).
        inv_init = [0] + [exp[(N - log[a]) % N] for a in range(1, N + 1)]
        self.specials.inv_rom = inv_rom = Memory(m_, N + 1, init=inv_init)
        inv_rp = inv_rom.get_port(async_read=True)
        self.specials += inv_rp
        # Received codeword and syndromes.
        cw   = Signal(n)
        S    = [Signal(m_, name=f"S{i}") for i in range(2*T)]
        idx  = Signal(max=n + 1)
        alpha_pow = [exp[i + 1] for i in range(2*T)]                    # alpha^(i+1).
        s_next = [_gf_mul(self, S[i], C(alpha_pow[i], m_), m_, poly) for i in range(2*T)]
        # Berlekamp-Massey state (binary: even steps have zero discrepancy).
        lam  = [Signal(m_, name=f"lam{i}") for i in range(T + 1)]      # Locator, lam[0] = 1.
        bpol = [Signal(m_, name=f"b{i}") for i in range(T + 1)]
        L    = Signal(max=T + 2)
        r_   = Signal(max=2*T + 1)                                      # BM iteration.
        d    = Signal(m_)                                               # Discrepancy.
        j_   = Signal(max=T + 2)                                        # Step within the iteration.
        acc  = Signal(m_)
        shift_b = Signal()                                              # b <- x*b vs b <- lam/d.
        dinv = Signal(m_)
        self.comb += [inv_rp.adr.eq(d), dinv.eq(inv_rp.dat_r)]
        # d = sum_{i=0..L} lam[i] * S[r - i]  (computed serially over j = 0..L).
        s_sel = Signal(m_)
        s_index = Signal(max=2*T + 1)
        self.comb += s_index.eq(r_ - j_)
        self.comb += s_sel.eq(Array(S)[s_index])
        lam_sel = Signal(m_)
        self.comb += lam_sel.eq(Array(lam)[j_])
        prod_d = _gf_mul(self, lam_sel, s_sel, m_, poly)
        # Update: lam[i] <- lam[i] ^ d * b[i-1]... implemented as lam <- lam + d * x * b with b
        # holding the shifted polynomial (b already multiplied by x each iteration).
        b_sel = Signal(m_)
        self.comb += b_sel.eq(Array(bpol)[j_])
        prod_u = _gf_mul(self, d, b_sel, m_, poly)
        lam_old = [Signal(m_, name=f"lamold{i}") for i in range(T + 1)]
        # Chien search.
        pos    = Signal(max=n + 1)
        chien  = [Signal(m_, name=f"ch{i}") for i in range(T + 1)]      # lam_i * alpha^(i * pos).
        ch_next = [_gf_mul(self, chien[i], C(exp[i % N] if i else 1, m_), m_, poly)
                                                 for i in range(T + 1)]
        ch_sum = Signal(m_)
        acc_sum = C(0, m_)
        for c in chien:
            acc_sum = acc_sum ^ c
        self.comb += ch_sum.eq(acc_sum)
        roots  = Signal(max=T + 2)
        mask   = Signal(n)
        # Output.
        emit = Signal()
        self.fsm = fsm = FSM(reset_state="RECEIVE")
        fsm.act("RECEIVE",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                NextValue(cw, Cat(cw[1:], self.sink.data)),
                *[NextValue(S[i], s_next[i] ^ Replicate(self.sink.data, m_)
                                                        & C(1, m_)) for i in range(2*T)],
                If(idx == n - 1,
                    NextValue(idx, 0),
                    NextState("CHECK"),
                ).Else(
                    NextValue(idx, idx + 1),
                ),
            ),
        )
        any_s = Signal()
        self.comb += any_s.eq(reduce_or(S))
        fsm.act("CHECK",
            NextValue(self.blocks, self.blocks + 1),
            *[NextValue(lam[i], 1 if i == 0 else 0) for i in range(T + 1)],
            *[NextValue(bpol[i], 1 if i == 0 else 0) for i in range(T + 1)],
            NextValue(L, 0), NextValue(r_, 0), NextValue(j_, 0), NextValue(acc, 0),
            NextValue(mask, 0), NextValue(roots, 0),
            If(any_s, NextState("BM_ACC")).Else(
                NextValue(self.corrected, 0), NextValue(idx, 0), NextState("OUT")),
        )
        # BM: for r = 0..2t-1: d = sum lam[j] S[r-j] (j = 0..L); if d != 0: lam' = lam + d x b;
        # if 2L <= r: b = lam_old / d, L = r + 1 - L else b = x b; (binary: only even r
        # matter, r counted from 0 with S index r).
        fsm.act("BM_ACC",
            If(j_ == L,
                NextValue(d, acc ^ prod_d), NextValue(j_, 0),
                *[NextValue(lam_old[i], lam[i]) for i in range(T + 1)],
                NextState("BM_UPD"),
            ).Else(
                NextValue(acc, acc ^ prod_d), NextValue(j_, j_ + 1),
            ),
        )
        fsm.act("BM_UPD",
            # lam[j] ^= d * b[j-1] serially over j = 1..T (b holds x-shifted values at index j-1).
            If(j_ == T,
                NextValue(j_, 0), NextValue(acc, 0),
                NextState("BM_B"),
            ).Else(
                If(d != 0,
                   *[If(j_ + 1 == i, NextValue(lam[i], lam[i] ^ prod_u)) for i in range(1, T + 1)]),
                NextValue(j_, j_ + 1),
            ),
        )
        fsm.act("BM_B",
            If((d != 0) & (2*L <= r_),
                # b <- lam_old / d, then shifted by x (the shift is folded into the index use).
                *[If(j_ == i, NextValue(bpol[i], _gf_mul(self, Array(lam_old)[j_], dinv, m_,
                                                         poly))) for i in range(T + 1)],
            ),
            If(j_ == T,
                NextValue(j_, 0),
                If((d != 0) & (2*L <= r_), NextValue(L, r_ + 1 - L)).Else(*[NextValue(bpol[i],
                    bpol[i - 1]) for i in range(1, T + 1)], NextValue(bpol[0], 0)),
                NextValue(r_, r_ + 1),
                If(r_ == 2*T - 1, NextState("BM_DONE")).Else(NextState("BM_ACC")),
            ).Else(
                NextValue(j_, j_ + 1),
            ),
        )
        fsm.act("BM_DONE",
            NextValue(pos, 0),
            *[NextValue(chien[i], lam[i]) for i in range(T + 1)],
            If(L > T,
                NextValue(self.uncorrectable, 1),
                NextValue(self.uncorrectable_count, self.uncorrectable_count + 1),
                NextValue(self.corrected, 0), NextValue(idx, 0), NextState("OUT"),
            ).Else(
                NextState("CHIEN"),
            ),
        )
        # Chien search over alpha^pos, pos = 0 .. n-1 (see chien_mask for the position map).
        fsm.act("CHIEN",
            If(ch_sum == 0,
                *[If(pos == p, NextValue(mask[p], 1)) for p in range(n)],
                NextValue(roots, roots + 1),
            ),
            *[NextValue(chien[i], ch_next[i]) for i in range(T + 1)],
            If(pos == n - 1,
                NextValue(idx, 0),
                NextState("FIX"),
            ).Else(
                NextValue(pos, pos + 1),
            ),
        )
        fsm.act("FIX",
            If(roots != L,
                NextValue(self.uncorrectable, 1),
                NextValue(self.uncorrectable_count, self.uncorrectable_count + 1),
                NextValue(self.corrected, 0),
            ).Else(
                NextValue(self.corrected, 1),
                NextValue(self.corrected_total, self.corrected_total + 1),
                NextValue(cw, cw ^ chien_mask(mask, n)),
            ),
            NextState("OUT"),
        )
        fsm.act("OUT",
            emit.eq(1),
            If(adv,
                If(idx == k - 1,
                    NextValue(idx, 0), *[NextValue(S[i], 0) for i in range(2*T)],
                    NextState("RECEIVE"),
                ).Else(
                    NextValue(idx, idx + 1),
                ),
            ),
        )
        self.sync += [
            If(adv,
                self.source.valid.eq(emit),
                self.source.data.eq(Array([cw[i] for i in range(n)])[idx]),
                self.source.first.eq(emit & (idx == 0)),
                self.source.last.eq(emit & (idx == k - 1)),
            ),
            If(self.clear, self.uncorrectable.eq(0)),
        ]
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=8, offset=0, description="Codeword bits."),
            CSRField("k", size=8, offset=8, description="Message bits."),
            CSRField("t", size=4, offset=16, description="Correctable errors."),
        ])
        self._control = CSRStorage(fields=[CSRField("clear", size=1, offset=0, pulse=True, description="Clear the uncorrectable flag.")])
        self._status  = CSRStatus(fields=[
            CSRField("corrected",     size=1, offset=0, description="The last block was corrected."),
            CSRField("uncorrectable", size=1, offset=1, description="Sticky: a block could not be corrected."),
        ])
        self._corrected_total     = CSRStatus(32, name="corrected_total",
                                              description="Blocks corrected.")
        self._uncorrectable_count = CSRStatus(32, name="uncorrectable_count",
                                              description="Uncorrectable blocks.")
        self._blocks = CSRStatus(32, name="blocks", description="Blocks decoded.")
        self.comb += [
            self._config.fields.n.eq(self.n), self._config.fields.k.eq(self.k),
            self._config.fields.t.eq(self.t),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.corrected.eq(self.corrected),
            self._status.fields.uncorrectable.eq(self.uncorrectable),
            self._corrected_total.status.eq(self.corrected_total),
            self._uncorrectable_count.status.eq(self.uncorrectable_count),
            self._blocks.status.eq(self.blocks),
        ]

def chien_mask(mask, n):
    """Root of the locator at ``alpha^p`` (Chien position ``p``) means an error at degree
    ``(n - p) mod n``; the received bit of degree ``e`` sits at index ``n - 1 - e``, so the
    error index is ``(p - 1) mod n``: bit ``i`` is flipped when position ``(i + 1) mod n`` was
    a root."""
    return Cat(*[mask[(i + 1) % n] for i in range(n)])

def reduce_or(terms):
    out = 0
    for t in terms:
        out = out | (t != 0)
    return out
