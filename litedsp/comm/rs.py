#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Reed-Solomon RS(255, k) codec over GF(2^8): systematic encoder + full hard-decision decoder.

The generic classes default to GF(2^8) polynomial 0x11D, primitive-root step 1 and first
consecutive root 0. ``LiteDSPCCSDSRSEncoder`` and ``LiteDSPCCSDSRSDecoder`` select the CCSDS
131.0-B-5 RS(255,223) profile (0x187, fcr=112, prim=11) and apply the required Berlekamp
dual-basis transforms at their stream boundaries.

Architecture (correctness-first, serial):

- Encoder: pass-through LFSR division by g(x) — k message bytes stream straight through while
  the 2t-stage parity register updates (one constant GF multiplier per stage), then the 2t
  parity bytes drain highest-degree first. Rate k-in/n-out, framed.
- Decoder: the n received bytes are written to a block RAM while 2t syndrome accumulators run
  (Horner, one constant multiplier each); a serial Berlekamp-Massey FSM (2t iterations, two
  (t+1)-byte register files, one term per cycle) finds the error locator; Omega = S*Lambda mod
  x^2t is accumulated serially; a serial Chien scan over all n positions evaluates Lambda,
  its odd part and Omega with constant-multiplier term registers, computing Forney magnitudes
  Omega(X^-1)/odd(Lambda(X^-1)) on the fly (GF inverse via log/antilog ROM lookups); located
  errors are read-modify-written into the RAM, then the k message bytes drain. Worst-case
  ``cycles_per_block`` = n + 2 + 2t(2t+3) + t(t+1)/2 + 1 + n + 2t + 2k + 2 (~2.25 kcycles,
  ~8.8n, for RS(255,223)) plus handshake stalls; the sink stalls while a block decodes/drains.

Block boundaries are counted from reset — sink ``first``/``last`` markers are ignored — and
each output block is framed with ``first``/``last``.
"""

from math import gcd

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check

# GF(2^8) Helpers ------------------------------------------------------------------------------------

GF_POLY = 0x11D  # x^8 + x^4 + x^3 + x^2 + 1, primitive, alpha = 2 (conventional basis; see module doc).
FCR     = 0      # First consecutive root: g(x) roots at alpha^0 .. alpha^(2t-1).
PRIM    = 1      # Consecutive-root exponent step.

CCSDS_GF_POLY = 0x187
CCSDS_FCR     = 112
CCSDS_PRIM    = 11

def _xor_tree(terms):
    """Balanced XOR reduction (cycle-neutral, logarithmic logic depth)."""
    level = list(terms)
    if not level:
        return 0
    while len(level) > 1:
        level = [level[i] ^ level[i + 1] if i + 1 < len(level) else level[i]
                 for i in range(0, len(level), 2)]
    return level[0]

def _gf_mul_int(a, b, poly=GF_POLY):
    """GF(2^8) product of two integers (Python-side: ROM init / constant folding)."""
    r = 0
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= poly
    return r

def _gf_tables(poly=GF_POLY):
    """Antilog/log tables: ``exp[i] = alpha^i`` (256 entries, ``exp[255] = exp[0]`` so the
    inverse address ``255 - log[x]`` stays in range), ``log[exp[i]] = i`` (``log[0]`` unused)."""
    exp = [0]*256
    log = [0]*256
    v = 1
    for i in range(255):
        exp[i] = v
        log[v] = i
        v = _gf_mul_int(v, 2, poly)
    exp[255] = 1
    return exp, log

def _rs_generator(n_parity, fcr=FCR, prim=PRIM, poly=GF_POLY):
    """Generator with roots ``alpha**((fcr+i)*prim)``, ascending coefficients (monic)."""
    exp, _ = _gf_tables(poly)
    g = [1]
    for i in range(n_parity):
        root = exp[((fcr + i)*prim) % 255]
        ng = [0]*(len(g) + 1)
        for j, c in enumerate(g):
            ng[j]     ^= _gf_mul_int(c, root, poly)
            ng[j + 1] ^= c
        g = ng
    return g

def _gf_mul_const(comb, x, c, poly=GF_POLY):
    """``x * c`` for a constant ``c``: a pure XOR network (one parity row per output bit)."""
    y    = Signal(8)
    cols = [_gf_mul_int(1 << j, c, poly) for j in range(8)]
    for i in range(8):
        taps = [x[j] for j in range(8) if (cols[j] >> i) & 1]
        comb += y[i].eq(_xor_tree(taps))
    return y

def _gf_mul(comb, a, b, poly=GF_POLY):
    """``a * b``, both variable: shift-and-reduce partial products (8 xtime levels)."""
    t     = a
    terms = []
    for i in range(8):
        if i:
            nt = Signal(8)
            comb += nt.eq(Cat(0, t[:7]) ^ Mux(t[7], C(poly & 0xFF, 8), C(0, 8)))
            t = nt
        term = Signal(8)
        comb += term.eq(Mux(b[i], t, C(0, 8)))
        terms.append(term)
    y = Signal(8)
    comb += y.eq(_xor_tree(terms))
    return y

def _rs_check(n, k):
    """Validate the (n, k) code parameters; return t = (n - k)/2."""
    check(n == 255, "expected n == 255 (native RS length over GF(2^8); no shortening support)")
    check(0 < k < n, "expected 0 < k < n")
    check((n - k) % 2 == 0, "expected even n - k (2t parity symbols)")
    t = (n - k)//2
    check(1 <= t <= 16, "expected t = (n - k)/2 in 1..16")
    return t

def _field_check(poly, fcr, prim):
    check(0x100 <= poly <= 0x1ff, "expected a degree-8 GF field polynomial")
    check(0 <= fcr < 255, "expected fcr in 0..254")
    check(1 <= prim < 255 and gcd(prim, 255) == 1,
        "expected prim in 1..254 and coprime with 255")
    exp, _ = _gf_tables(poly)
    check(len(set(exp[:255])) == 255, "field polynomial is not primitive for alpha=2")

def _ccsds_basis_tables():
    """Conventional-alpha <-> CCSDS Berlekamp dual-basis symbol maps."""
    tal = (0x8d, 0xef, 0xec, 0x86, 0xfa, 0x99, 0xaf, 0x7b)
    to_dual = [0]*256
    to_conventional = [0]*256
    for value in range(256):
        mapped = 0
        for bit in range(8):
            if value & (1 << bit):
                mapped ^= tal[7 - bit]
        to_dual[value] = mapped
        to_conventional[mapped] = value
    return to_dual, to_conventional

CCSDS_TO_DUAL, CCSDS_TO_CONVENTIONAL = _ccsds_basis_tables()

def _linear_map(comb, value, table):
    """Synthesize an 8x8 GF(2) map represented by its 256-entry Python lookup table."""
    result = Signal(8)
    columns = [table[1 << bit] for bit in range(8)]
    for out_bit in range(8):
        taps = [value[in_bit] for in_bit in range(8) if (columns[in_bit] >> out_bit) & 1]
        comb += result[out_bit].eq(_xor_tree(taps))
    return result

# RS Encoder -----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPRSEncoder(LiteXModule):
    """Systematic RS(255, k) encoder: k message bytes in, n = 255 codeword bytes out.

    The k message bytes pass straight through (highest-degree coefficient first) while a
    2t-stage LFSR divides by g(x); the 2t parity bytes then drain highest-degree first.
    Message boundaries are counted from reset (sink ``first``/``last`` ignored); the output
    codeword is framed with ``first``/``last``. See the module docstring for the field and
    generator-polynomial conventions. Symbols use the conventional polynomial basis; use
    ``LiteDSPCCSDSRSEncoder`` for the standard CCSDS dual-basis stream representation.

    Parameters
    ----------
    n : int
        Codeword length in symbols (bytes); fixed at 255, the native RS length over GF(2^8).
    k : int
        Message length in symbols; n - k = 2t parity symbols are appended (n - k even,
        t = (n - k)/2 in 1..16; default RS(255, 223), t = 16).
    field_poly : int
        Degree-8 primitive field polynomial (default 0x11D).
    fcr : int
        First consecutive generator-root index (default 0).
    prim : int
        Root exponent step, coprime with 255 (default 1).
    """
    def __init__(self, n=255, k=223, with_csr=True, field_poly=GF_POLY, fcr=FCR, prim=PRIM):
        t = _rs_check(n, k)
        _field_check(field_poly, fcr, prim)
        self.n = n
        self.k = k
        self.t = t
        self.field_poly = field_poly
        self.fcr = fcr
        self.prim = prim
        self.latency = None  # Variable rate (k bytes in -> n bytes out, framed).
        self.sink   = stream.Endpoint([("data", 8)])
        self.source = stream.Endpoint([("data", 8)])

        # # #

        n_par = n - k
        g     = _rs_generator(n_par, fcr=fcr, prim=prim, poly=field_poly)

        # Parity LFSR.
        # ------------
        # Standard systematic-encoder division register: p[i] holds the coefficient of x^i of
        # m(x)*x^2t mod g(x) once the k message bytes have been absorbed.
        p    = [Signal(8) for _ in range(n_par)]
        fb   = Signal(8)
        self.comb += fb.eq(self.sink.data ^ p[-1])
        fb_g = [_gf_mul_const(self.comb, fb, g[i], field_poly) for i in range(n_par)]

        # FSM.
        # ----
        cnt = Signal(max=n)  # Byte position within the codeword.
        self.fsm = fsm = FSM(reset_state="MESSAGE")
        fsm.act("MESSAGE",  # Pass k message bytes through while dividing by g(x).
            self.sink.ready.eq(self.source.ready),
            self.source.valid.eq(self.sink.valid),
            self.source.data.eq(self.sink.data),
            self.source.first.eq(cnt == 0),
            If(self.sink.valid & self.source.ready,
                *[NextValue(p[i], (p[i - 1] if i else 0) ^ fb_g[i]) for i in range(n_par)],
                NextValue(cnt, cnt + 1),
                If(cnt == (k - 1), NextState("PARITY")),
            )
        )
        fsm.act("PARITY",  # Drain the 2t parity bytes, highest degree first.
            self.source.valid.eq(1),
            self.source.data.eq(p[-1]),
            self.source.last.eq(cnt == (n - 1)),
            If(self.source.ready,
                *[NextValue(p[i], p[i - 1] if i else 0) for i in range(n_par)],
                If(cnt == (n - 1),
                    NextValue(cnt, 0),
                    NextState("MESSAGE"),  # LFSR is all-zero again after the 2t shifts.
                ).Else(NextValue(cnt, cnt + 1)),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=9, description="Codeword length in symbols."),
            CSRField("k", size=8, description="Message length in symbols."),
            CSRField("t", size=5, description="Correctable symbols per codeword."),
        ])
        self.comb += [
            self._config.fields.n.eq(self.n),
            self._config.fields.k.eq(self.k),
            self._config.fields.t.eq(self.t),
        ]

# RS Decoder -----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPRSDecoder(LiteXModule):
    """RS(255, k) decoder: n = 255 codeword bytes in, k corrected message bytes out.

    Full hard-decision decode — syndromes, serial Berlekamp-Massey, serial Chien search with
    on-the-fly Forney magnitudes — correcting up to t = (n - k)/2 symbol errors per block
    (see the module docstring for the architecture and the worst-case ``cycles_per_block``).
    A block beyond the correction capability (locator degree > t, or Chien root count not
    matching the locator degree) is passed through *uncorrected* and flagged: ``uncorrectable``
    (sticky) is set and ``uncorrectable_count`` increments. ``corrected`` reports the symbols
    corrected in the last block (message + parity positions), ``corrected_total`` accumulates;
    ``clear`` resets the sticky flag and the cumulative counters. Block boundaries are counted
    from reset (sink ``first``/``last`` ignored); output blocks are framed with ``first``/``last``.

    Parameters
    ----------
    n : int
        Codeword length in symbols (bytes); fixed at 255, the native RS length over GF(2^8).
    k : int
        Message length in symbols; t = (n - k)/2 symbol errors per block are correctable
        (n - k even, t in 1..16; default RS(255, 223), t = 16).
    architecture : str
        ``"classic"`` evaluates and advances one Chien position per clock. ``"pipelined"``
        registers operands for the Berlekamp-Massey discrepancy and update multipliers before
        their recurrences, and Lambda's odd/even evaluation plus Omega before the inverse/Forney
        product. It adds discrepancy/update/inversion and Omega drain clocks plus three clocks per
        Chien position, while preserving the correction algorithm and all output/status behavior.
    field_poly, fcr, prim : int
        Conventional-basis field polynomial, first consecutive root and root exponent step.
    """
    def __init__(self, n=255, k=223, with_csr=True, architecture="classic",
        field_poly=GF_POLY, fcr=FCR, prim=PRIM):
        t = _rs_check(n, k)
        _field_check(field_poly, fcr, prim)
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        self.n = n
        self.k = k
        self.t = t
        self.architecture = architecture
        self.field_poly = field_poly
        self.fcr = fcr
        self.prim = prim
        self.latency = None  # Variable (framed block decode; see cycles_per_block).
        # Worst-case decode cycles per block (receive + check + BM + Omega + Chien init/scan +
        # apply + drain), excluding handshake stalls.
        pipeline_cycles = (3*n + 7*t)*int(architecture == "pipelined")
        self.cycles_per_block = (n + 2 + 2*t*(2*t + 3) + t*(t + 1)//2 + 1 + n +
            pipeline_cycles + 2*t + 2*k + 2)
        self.sink   = stream.Endpoint([("data", 8)])
        self.source = stream.Endpoint([("data", 8)])
        self.corrected           = Signal(max=t + 1)  # Symbols corrected in the last block.
        self.corrected_total     = Signal(32)         # Cumulative corrected symbols since clear.
        self.uncorrectable       = Signal()           # Sticky: a block exceeded capability.
        self.uncorrectable_count = Signal(16)         # Uncorrectable blocks since clear.
        self.clear               = Signal()           # Clear the sticky flag + cumulative counters.

        # # #

        n_par    = n - k
        exp, log = _gf_tables(field_poly)

        # Memories.
        # ---------
        # Codeword buffer: one block, single R/W port (receive / correct-RMW / drain are
        # serialized by the FSM). Log/antilog ROMs give the GF inverse x^-1 = alpha^(255 - log x)
        # used by the Berlekamp-Massey division and the Forney magnitudes.
        buf = Memory(8, n)
        bp  = buf.get_port(write_capable=True)
        log_rom = Memory(8, 256, init=log)
        exp_rom = Memory(8, 256, init=exp)  # exp[255] = exp[0] = 1: 255 - log[x] stays in range.
        log_rp  = log_rom.get_port(async_read=True)
        exp_rp  = exp_rom.get_port(async_read=True)
        self.specials += buf, bp, log_rom, exp_rom, log_rp, exp_rp

        inv_in  = Signal(8)  # Inverse operand (BM: b, Chien/Forney: odd Lambda sum).
        inv_x   = Signal(8)  # Multiplicand of the shared (x * inv_in^-1) product.
        inv_in_reg = Signal(8)
        inv_x_reg  = Signal(8)
        inv_operand = inv_in_reg if architecture == "pipelined" else inv_in
        mul_operand = inv_x_reg  if architecture == "pipelined" else inv_x
        self.comb += [
            log_rp.adr.eq(inv_operand),
            exp_rp.adr.eq(255 - log_rp.dat_r),
        ]
        inv_mul = _gf_mul(self.comb, mul_operand, exp_rp.dat_r, field_poly)

        # Syndromes.
        # ----------
        # Horner accumulators S_i = r(alpha^(fcr+i)): one constant multiplier each, updated on
        # every accepted byte (arrival order = highest-degree coefficient first).
        synd    = Array(Signal(8) for _ in range(n_par))
        s_next  = []
        for i in range(n_par):
            prod = _gf_mul_const(self.comb, synd[i],
                exp[((fcr + i)*prim) % 255], field_poly)
            s    = Signal(8)
            self.comb += s.eq(prod ^ self.sink.data)
            s_next.append(s)
        synd_nz = Signal()
        self.comb += synd_nz.eq(Cat(*[s != 0 for s in synd]) != 0)

        # Berlekamp-Massey state.
        # -----------------------
        # Two (t+1)-byte register files (locator lambda and helper B), truncated at degree t;
        # one discrepancy/update term per cycle (serial sweeps over j).
        lam   = Array(Signal(8, reset=(1 if i == 0 else 0)) for i in range(t + 1))
        bpol  = Array(Signal(8, reset=(1 if i == 0 else 0)) for i in range(t + 1))
        r_i   = Signal(max=n_par)               # BM iteration (0..2t-1).
        j     = Signal(max=t + 2)               # Serial sweep index (0..t).
        l_i   = Signal(max=t + 1)               # Omega inner index (0..j).
        L     = Signal(max=2*t + 1)             # Locator degree estimate.
        m     = Signal(max=2*t + 2, reset=1)    # Shift since the last B update.
        b_reg = Signal(8, reset=1)              # Discrepancy at the last B update.
        d     = Signal(8)                       # Discrepancy accumulator.
        disc_a = Signal(8)                      # Registered operands in the pipelined BM schedule.
        disc_b = Signal(8)
        disc_valid = Signal()
        coef  = Signal(8)                       # d/b for the update sweep.
        swap  = Signal()                        # 2L <= r at this update: B takes the old lambda.
        upd_b_reg = Signal(8)
        upd_lam_reg = Signal(8)
        upd_idx = Signal(max=t + 1)
        upd_valid = Signal()

        # Discrepancy term lambda[j]*S[r-j] (gated to 0 when j > r).
        s_idx = Signal(max=n_par)
        s_rj  = Signal(8)
        lam_j = Signal(8)
        self.comb += [
            If(j <= r_i, s_idx.eq(r_i - j), s_rj.eq(synd[s_idx])),
            lam_j.eq(lam[j]),
        ]
        disc_term = _gf_mul(self.comb, lam_j, s_rj, field_poly)
        disc_registered_term = _gf_mul(self.comb, disc_a, disc_b, field_poly)

        # Update term coef*B[j-m] (gated to 0 when j < m).
        b_idx = Signal(max=t + 1)
        b_sel = Signal(8)
        self.comb += If(j >= m, b_idx.eq(j - m), b_sel.eq(bpol[b_idx]))
        upd_term = _gf_mul(self.comb, coef, b_sel, field_poly)
        upd_registered_term = _gf_mul(self.comb, coef, upd_b_reg, field_poly)
        bm_write_idx = upd_idx if architecture == "pipelined" else j
        bm_write_lam = upd_lam_reg if architecture == "pipelined" else lam_j
        bm_write_term = upd_registered_term if architecture == "pipelined" else upd_term

        # Omega (error evaluator).
        # ------------------------
        # Omega = S(x)*lambda(x) mod x^2t, degree <= t-1: one S[l]*lambda[j-l] term per cycle.
        omg   = Array(Signal(8) for _ in range(t))
        acc   = Signal(8)
        omg_a = Signal(8)
        omg_b = Signal(8)
        omg_valid = Signal()
        jl    = Signal(max=t + 1)
        s_l   = Signal(8)
        lam_jl = Signal(8)
        self.comb += [
            jl.eq(j - l_i),                     # l_i <= j in the OMEGA state.
            s_l.eq(synd[l_i]),
            lam_jl.eq(lam[jl]),
        ]
        omg_term = _gf_mul(self.comb, s_l, lam_jl, field_poly)
        omg_registered_term = _gf_mul(self.comb, omg_a, omg_b, field_poly)
        omg_write_value = Signal(8)
        self.comb += omg_write_value.eq(acc ^ (
            omg_registered_term if architecture == "pipelined" else omg_term))

        # Chien / Forney.
        # ---------------
        # Term registers q[j] = lambda[j]*alpha^(-prim*i*j) and
        # o[j] = Omega[j]*alpha^(-prim*i*j), stepped by constant alpha^(-prim*j)
        # multipliers; lambda(alpha^(-prim*i)) = even ^ odd, and a zero marks an
        # error at codeword position i (buffer index n-1-i) with Forney magnitude
        # x^fcr*Omega(x)/odd, x = alpha^(-prim*i).
        q = Array(Signal(8) for _ in range(t + 1))
        o = Array(Signal(8) for _ in range(t))
        q_next = [_gf_mul_const(self.comb, q[i], exp[(-prim*i) % 255], field_poly)
                  for i in range(t + 1)]
        o_next = [_gf_mul_const(self.comb, o[i], exp[(-prim*i) % 255], field_poly)
                  for i in range(t)]
        even_terms = [q[i] for i in range(0, t + 1, 2)]
        odd_terms  = [q[i] for i in range(1, t + 1, 2)]
        omega_terms = [o[i] for i in range(t)]
        even    = Signal(8)
        odd     = Signal(8)
        om_val  = Signal(8)
        lam_val = Signal(8)
        self.comb += [
            even.eq(_xor_tree(even_terms)),
            odd.eq(_xor_tree(odd_terms)),
            om_val.eq(_xor_tree(omega_terms)),
            lam_val.eq(even ^ odd),
        ]
        x_fcr      = Signal(8, reset=1)
        x_fcr_next = _gf_mul_const(self.comb, x_fcr,
            exp[(-prim*fcr) % 255], field_poly)
        forney_num = _gf_mul(self.comb, om_val, x_fcr, field_poly) if fcr else om_val
        pos      = Signal(max=n)                       # Chien position i (X = alpha^i).
        roots    = Signal(max=t + 1)                   # Located errors this block.
        rr       = Signal(max=t + 1)                   # Apply index.
        anomaly  = Signal()                            # Zero odd part at a root: force uncorrectable.
        root_idx = Array(Signal(8) for _ in range(t))  # Buffer index of each located error.
        root_mag = Array(Signal(8) for _ in range(t))  # Forney magnitude of each located error.
        chien_odd = Signal(8)
        chien_om  = Signal(8)
        chien_lam = Signal(8)
        chien_mag = Signal(8)
        chien_even_lo = Signal(8)
        chien_even_hi = Signal(8)
        chien_odd_lo  = Signal(8)
        chien_odd_hi  = Signal(8)
        chien_om_lo   = Signal(8)
        chien_om_hi   = Signal(8)
        chien_scale   = Signal(8, reset=1)

        def _halves(terms):
            split = (len(terms) + 1)//2
            return _xor_tree(terms[:split]), _xor_tree(terms[split:])

        even_lo, even_hi = _halves(even_terms)
        odd_lo,  odd_hi  = _halves(odd_terms)
        om_lo,   om_hi   = _halves(omega_terms)
        chien_om_sum = chien_om_lo ^ chien_om_hi
        chien_num = _gf_mul(self.comb, chien_om_sum, chien_scale, field_poly) \
            if fcr else chien_om_sum
        root_write_mag = chien_mag if architecture == "pipelined" else inv_mul

        # Register-file writes with a computed index (FSM-enabled, expanded to per-index write
        # enables: keeps the generated Verilog free of blocking sequential assignments).
        bm_upd  = Signal()  # BM_UPDATE sweep step.
        omg_we  = Signal()  # OMEGA coefficient store.
        root_we = Signal()  # CHIEN root record.
        self.sync += [
            *[If(bm_upd & (bm_write_idx == i),
                lam[i].eq(bm_write_lam ^ bm_write_term),
                If(swap, bpol[i].eq(bm_write_lam)),
              ) for i in range(t + 1)],
            *[If(omg_we & (j == i), omg[i].eq(omg_write_value)) for i in range(t)],
            *[If(root_we & (roots == i),
                root_idx[i].eq((n - 1) - pos),
                root_mag[i].eq(root_write_mag),
              ) for i in range(t)],
        ]

        # Status counters.
        # ----------------
        blk_clean  = Signal()  # Pulses: block done with zero syndromes,
        blk_fixed  = Signal()  #         block corrected (roots applied),
        blk_uncorr = Signal()  #         block beyond capability (passed through raw).
        self.sync += [
            If(blk_clean | blk_uncorr, self.corrected.eq(0)),
            If(blk_fixed,
                self.corrected.eq(roots),
                self.corrected_total.eq(self.corrected_total + roots),
            ),
            If(blk_uncorr,
                self.uncorrectable.eq(1),
                self.uncorrectable_count.eq(self.uncorrectable_count + 1),
            ),
            If(self.clear,
                self.corrected_total.eq(0),
                self.uncorrectable.eq(0),
                self.uncorrectable_count.eq(0),
            ),
        ]

        # FSM.
        # ----
        idx = Signal(max=n)  # Buffer address (receive / drain).
        self.fsm = fsm = FSM(reset_state="RECEIVE")
        fsm.act("RECEIVE",  # Buffer the n bytes while the syndrome accumulators run.
            self.sink.ready.eq(1),
            bp.adr.eq(idx),
            bp.dat_w.eq(self.sink.data),
            bp.we.eq(self.sink.valid),
            If(self.sink.valid,
                *[NextValue(synd[i], s_next[i]) for i in range(n_par)],
                If(idx == (n - 1),
                    NextValue(idx, 0),
                    NextState("CHECK"),
                ).Else(NextValue(idx, idx + 1)),
            )
        )
        fsm.act("CHECK",  # Clean-block fast path + Berlekamp-Massey state (re-)init.
            *[NextValue(lam[i],  1 if i == 0 else 0) for i in range(t + 1)],
            *[NextValue(bpol[i], 1 if i == 0 else 0) for i in range(t + 1)],
            *[NextValue(omg[i], 0) for i in range(t)],
            NextValue(L, 0), NextValue(m, 1), NextValue(b_reg, 1),
            NextValue(r_i, 0), NextValue(j, 0), NextValue(l_i, 0),
            NextValue(d, 0), NextValue(acc, 0),
            NextValue(roots, 0), NextValue(rr, 0), NextValue(anomaly, 0),
            If(synd_nz,
                NextState("BM_DISC"),
            ).Else(
                blk_clean.eq(1),
                NextState("OUT_READ"),
            )
        )
        bm_last = (r_i == (n_par - 1))
        if architecture == "classic":
            fsm.act("BM_DISC",  # d = sum lambda[j]*S[r-j], one term per cycle.
                NextValue(d, d ^ disc_term),
                If(j == t, NextState("BM_CALC")).Else(NextValue(j, j + 1)),
            )
        else:
            fsm.act("BM_DISC",  # Capture one term's operands; accumulate the preceding term.
                NextValue(disc_a, lam_j),
                NextValue(disc_b, s_rj),
                NextValue(disc_valid, 1),
                If(disc_valid, NextValue(d, d ^ disc_registered_term)),
                If(j == t, NextState("BM_DISC_DRAIN")).Else(NextValue(j, j + 1)),
            )
            fsm.act("BM_DISC_DRAIN",
                If(disc_valid, NextValue(d, d ^ disc_registered_term)),
                NextValue(disc_valid, 0),
                NextState("BM_CALC"),
            )
        def bm_calc_body():
            return [
                NextValue(coef, inv_mul),
                NextValue(swap, (2*L) <= r_i),
                If(d == 0,
                    NextValue(m, m + 1),
                    NextValue(j, 0),
                    If(bm_last, NextState("BM_DONE")).Else(
                        NextValue(r_i, r_i + 1), NextState("BM_DISC")),
                ).Else(
                    NextValue(j, t),
                    NextState("BM_UPDATE"),
                ),
            ]

        if architecture == "classic":
            fsm.act("BM_CALC",  # coef = d/b; zero discrepancy skips the update.
                inv_in.eq(b_reg),
                inv_x.eq(d),
                *bm_calc_body(),
            )
        else:
            fsm.act("BM_CALC",
                NextValue(inv_in_reg, b_reg),
                NextValue(inv_x_reg, d),
                NextState("BM_CALC_COMMIT"),
            )
            fsm.act("BM_CALC_COMMIT", *bm_calc_body())
        if architecture == "classic":
            fsm.act("BM_UPDATE",  # Descending lambda[j] ^= coef*B[j-m] sweep.
                bm_upd.eq(1),
                If(j == 0,
                    NextValue(d, 0),
                    If(swap,
                        NextValue(b_reg, d),
                        NextValue(L, r_i + 1 - L),
                        NextValue(m, 1),
                    ).Else(NextValue(m, m + 1)),
                    If(bm_last, NextState("BM_DONE")).Else(NextValue(r_i, r_i + 1), NextState("BM_DISC")),
                ).Else(NextValue(j, j - 1)),
            )
        else:
            fsm.act("BM_UPDATE",  # Capture current operands; commit the preceding coefficient.
                NextValue(upd_b_reg, b_sel),
                NextValue(upd_lam_reg, lam_j),
                NextValue(upd_idx, j),
                NextValue(upd_valid, 1),
                If(upd_valid, bm_upd.eq(1)),
                If(j == 0, NextState("BM_UPDATE_DRAIN")).Else(NextValue(j, j - 1)),
            )
            fsm.act("BM_UPDATE_DRAIN",
                If(upd_valid, bm_upd.eq(1)),
                NextValue(upd_valid, 0),
                NextValue(d, 0),
                If(swap,
                    NextValue(b_reg, d),
                    NextValue(L, r_i + 1 - L),
                    NextValue(m, 1),
                ).Else(NextValue(m, m + 1)),
                If(bm_last, NextState("BM_DONE")).Else(NextValue(r_i, r_i + 1), NextState("BM_DISC")),
            )
        fsm.act("BM_DONE",  # Locator degree beyond t: uncorrectable, skip Chien.
            NextValue(j, 0), NextValue(l_i, 0), NextValue(acc, 0),
            If(L > t, NextState("UNCORR")).Else(NextState("OMEGA")),
        )
        if architecture == "classic":
            fsm.act("OMEGA",  # Omega[j] = sum S[l]*lambda[j-l], one term per cycle.
                If(l_i == j,
                    omg_we.eq(1),
                    NextValue(acc, 0),
                    NextValue(l_i, 0),
                    If(j == (t - 1), NextState("CHIEN_INIT")).Else(NextValue(j, j + 1)),
                ).Else(
                    NextValue(acc, acc ^ omg_term),
                    NextValue(l_i, l_i + 1),
                )
            )
        else:
            fsm.act("OMEGA",  # Capture one term's operands; accumulate the preceding term.
                NextValue(omg_a, s_l),
                NextValue(omg_b, lam_jl),
                NextValue(omg_valid, 1),
                If(omg_valid, NextValue(acc, acc ^ omg_registered_term)),
                If(l_i == j, NextState("OMEGA_DRAIN")).Else(NextValue(l_i, l_i + 1)),
            )
            fsm.act("OMEGA_DRAIN",
                omg_we.eq(1),
                NextValue(acc, 0),
                NextValue(l_i, 0),
                NextValue(omg_valid, 0),
                If(j == (t - 1), NextState("CHIEN_INIT")).Else(NextValue(j, j + 1), NextState("OMEGA")),
            )
        fsm.act("CHIEN_INIT",  # Load the term registers for position i = 0 (X = alpha^0).
            *[NextValue(q[i], lam[i]) for i in range(t + 1)],
            *[NextValue(o[i], omg[i]) for i in range(t)],
            NextValue(pos, 0),
            NextValue(x_fcr, 1),
            NextState("CHIEN" if architecture == "classic" else "CHIEN_EVAL"),
        )
        if architecture == "classic":
            fsm.act("CHIEN",  # One position per cycle: evaluate, record roots + Forney magnitudes.
                inv_in.eq(odd),
                inv_x.eq(forney_num),
                If(lam_val == 0,
                    If(odd == 0,
                        NextValue(anomaly, 1),          # Degenerate (repeated root): uncorrectable.
                    ).Elif(roots != t,
                        root_we.eq(1),
                        NextValue(roots, roots + 1),
                    ),
                ),
                *[NextValue(q[i], q_next[i]) for i in range(t + 1)],
                *[NextValue(o[i], o_next[i]) for i in range(t)],
                NextValue(x_fcr, x_fcr_next),
                If(pos == (n - 1), NextState("CHIEN_DONE")).Else(NextValue(pos, pos + 1)),
            )
        else:
            fsm.act("CHIEN_EVAL",  # Register half reductions; advance term registers.
                NextValue(chien_even_lo, even_lo),
                NextValue(chien_even_hi, even_hi),
                NextValue(chien_odd_lo,  odd_lo),
                NextValue(chien_odd_hi,  odd_hi),
                NextValue(chien_om_lo,   om_lo),
                NextValue(chien_om_hi,   om_hi),
                NextValue(chien_scale,   x_fcr),
                *[NextValue(q[i], q_next[i]) for i in range(t + 1)],
                *[NextValue(o[i], o_next[i]) for i in range(t)],
                NextValue(x_fcr, x_fcr_next),
                NextState("CHIEN_REDUCE"),
            )
            fsm.act("CHIEN_REDUCE",
                NextValue(chien_odd, chien_odd_lo ^ chien_odd_hi),
                NextValue(chien_om,  chien_om_lo ^ chien_om_hi),
                NextValue(chien_lam, chien_even_lo ^ chien_even_hi ^ chien_odd_lo ^ chien_odd_hi),
                NextValue(inv_in_reg, chien_odd_lo ^ chien_odd_hi),
                NextValue(inv_x_reg, chien_num),
                NextState("CHIEN_FORNEY"),
            )
            fsm.act("CHIEN_FORNEY",
                NextValue(chien_mag, inv_mul),
                NextState("CHIEN_COMMIT"),
            )
            fsm.act("CHIEN_COMMIT",  # Inverse/Forney product from registered evaluation.
                If(chien_lam == 0,
                    If(chien_odd == 0,
                        NextValue(anomaly, 1),
                    ).Elif(roots != t,
                        root_we.eq(1),
                        NextValue(roots, roots + 1),
                    ),
                ),
                If(pos == (n - 1),
                    NextState("CHIEN_DONE"),
                ).Else(
                    NextValue(pos, pos + 1),
                    NextState("CHIEN_EVAL"),
                ),
            )
        fsm.act("CHIEN_DONE",  # Root count must match the locator degree exactly.
            If((roots == L) & ~anomaly,
                NextState("APPLY_READ"),
            ).Else(NextState("UNCORR")),
        )
        fsm.act("APPLY_READ",  # Issue the buffer read of the next error location.
            bp.adr.eq(root_idx[rr]),
            NextState("APPLY_WRITE"),
        )
        fsm.act("APPLY_WRITE",  # Read-modify-write: buf[loc] ^= magnitude.
            bp.adr.eq(root_idx[rr]),
            bp.dat_w.eq(bp.dat_r ^ root_mag[rr]),
            bp.we.eq(1),
            If(rr == (roots - 1),
                blk_fixed.eq(1),
                NextState("OUT_READ"),
            ).Else(NextValue(rr, rr + 1), NextState("APPLY_READ")),
        )
        fsm.act("UNCORR",  # Beyond capability: flag it, pass the received message through raw.
            blk_uncorr.eq(1),
            NextState("OUT_READ"),
        )
        fsm.act("OUT_READ",  # Issue the buffer read of message byte idx.
            bp.adr.eq(idx),
            NextState("OUT_EMIT"),
        )
        fsm.act("OUT_EMIT",  # Emit it (address held: registered read data stays stable).
            bp.adr.eq(idx),
            self.source.valid.eq(1),
            self.source.data.eq(bp.dat_r),
            self.source.first.eq(idx == 0),
            self.source.last.eq(idx == (k - 1)),
            If(self.source.ready,
                If(idx == (k - 1),
                    NextValue(idx, 0),
                    *[NextValue(synd[i], 0) for i in range(n_par)],
                    NextState("RECEIVE"),
                ).Else(NextValue(idx, idx + 1), NextState("OUT_READ")),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=9, description="Codeword length in symbols."),
            CSRField("k", size=8, description="Message length in symbols."),
            CSRField("t", size=5, description="Correctable symbols per codeword."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("corrected",     size=8, description="Symbols corrected in the last decoded block."),
            CSRField("uncorrectable", size=1, description="Sticky: a block exceeded the correction capability since clear."),
        ])
        self._corrected_total     = CSRStatus(32, description="Cumulative corrected symbols since clear.")
        self._uncorrectable_count = CSRStatus(16, description="Uncorrectable blocks since clear.")
        self._clear               = CSRStorage(1, description="Clear the sticky flag and the cumulative counters (write to clear).")
        self.comb += [
            self._config.fields.n.eq(self.n),
            self._config.fields.k.eq(self.k),
            self._config.fields.t.eq(self.t),
            self._status.fields.corrected.eq(self.corrected),
            self._status.fields.uncorrectable.eq(self.uncorrectable),
            self._corrected_total.status.eq(self.corrected_total),
            self._uncorrectable_count.status.eq(self.uncorrectable_count),
            self.clear.eq(self._clear.re),
        ]

# CCSDS Dual-Basis Wrappers -------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCCSDSRSEncoder(LiteXModule):
    """CCSDS 131.0-B-5 RS(255,223) encoder with dual-basis stream symbols.

    The stream-facing linear maps convert incoming dual-basis message symbols to the
    conventional-alpha representation used by the generic encoder and convert its systematic
    codeword back to dual basis. They add no cycles and preserve framing/backpressure exactly.
    """
    def __init__(self, with_csr=True):
        self.n = 255
        self.k = 223
        self.t = 16
        self.latency = None
        self.sink   = stream.Endpoint([("data", 8)])
        self.source = stream.Endpoint([("data", 8)])

        # # #

        self.encoder = encoder = LiteDSPRSEncoder(
            n=self.n, k=self.k, field_poly=CCSDS_GF_POLY,
            fcr=CCSDS_FCR, prim=CCSDS_PRIM, with_csr=False)
        sink_data   = _linear_map(self.comb, self.sink.data, CCSDS_TO_CONVENTIONAL)
        source_data = _linear_map(self.comb, encoder.source.data, CCSDS_TO_DUAL)
        self.comb += [
            self.sink.connect(encoder.sink, omit={"data"}),
            encoder.sink.data.eq(sink_data),
            encoder.source.connect(self.source, omit={"data"}),
            self.source.data.eq(source_data),
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=9, description="Codeword length in symbols."),
            CSRField("k", size=8, description="Message length in symbols."),
            CSRField("t", size=5, description="Correctable symbols per codeword."),
        ])
        self.comb += [
            self._config.fields.n.eq(self.n),
            self._config.fields.k.eq(self.k),
            self._config.fields.t.eq(self.t),
        ]


@ResetInserter()
class LiteDSPCCSDSRSDecoder(LiteXModule):
    """CCSDS 131.0-B-5 RS(255,223) decoder with dual-basis stream symbols.

    Input/output basis conversion is combinational and cycle-neutral. ``architecture`` selects
    the same classic or timing-oriented pipelined schedule as ``LiteDSPRSDecoder``.
    """
    def __init__(self, with_csr=True, architecture="pipelined"):
        self.n = 255
        self.k = 223
        self.t = 16
        self.architecture = architecture
        self.latency = None
        self.sink   = stream.Endpoint([("data", 8)])
        self.source = stream.Endpoint([("data", 8)])

        # # #

        self.decoder = decoder = LiteDSPRSDecoder(
            n=self.n, k=self.k, architecture=architecture,
            field_poly=CCSDS_GF_POLY, fcr=CCSDS_FCR, prim=CCSDS_PRIM, with_csr=False)
        self.cycles_per_block = decoder.cycles_per_block
        self.corrected           = decoder.corrected
        self.corrected_total     = decoder.corrected_total
        self.uncorrectable       = decoder.uncorrectable
        self.uncorrectable_count = decoder.uncorrectable_count
        self.clear               = decoder.clear

        sink_data   = _linear_map(self.comb, self.sink.data, CCSDS_TO_CONVENTIONAL)
        source_data = _linear_map(self.comb, decoder.source.data, CCSDS_TO_DUAL)
        self.comb += [
            self.sink.connect(decoder.sink, omit={"data"}),
            decoder.sink.data.eq(sink_data),
            decoder.source.connect(self.source, omit={"data"}),
            self.source.data.eq(source_data),
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=9, description="Codeword length in symbols."),
            CSRField("k", size=8, description="Message length in symbols."),
            CSRField("t", size=5, description="Correctable symbols per codeword."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("corrected", size=8,
                description="Symbols corrected in the last decoded block."),
            CSRField("uncorrectable", size=1,
                description="Sticky: a block exceeded the correction capability since clear."),
        ])
        self._corrected_total = CSRStatus(32,
            description="Cumulative corrected symbols since clear.")
        self._uncorrectable_count = CSRStatus(16,
            description="Uncorrectable blocks since clear.")
        self._clear = CSRStorage(1,
            description="Clear the sticky flag and cumulative counters (write to clear).")
        self.comb += [
            self._config.fields.n.eq(self.n),
            self._config.fields.k.eq(self.k),
            self._config.fields.t.eq(self.t),
            self._status.fields.corrected.eq(self.corrected),
            self._status.fields.uncorrectable.eq(self.uncorrectable),
            self._corrected_total.status.eq(self.corrected_total),
            self._uncorrectable_count.status.eq(self.uncorrectable_count),
            self.clear.eq(self._clear.re),
        ]
