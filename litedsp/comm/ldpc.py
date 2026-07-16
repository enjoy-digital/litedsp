#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LDPC codec for the IEEE 802.11n rate-1/2 (n=648, z=27) quasi-cyclic code.

Code: the 12x24 base (prototype) matrix of IEEE 802.11-2012 Annex F, Table F-1, first code
(n = 648, rate 1/2, z = 27) — embedded below as ``LDPC_BASE``. Entry -1 is an all-zero
27x27 block; entry s >= 0 is the identity cyclically shifted by s, i.e. block row r has its
one at column (r + s) mod 27. k = 324 message bits, 324 parity bits. The parity part is the
standard dual-diagonal structure: one special column (block column 12, shifts (1, 0, 1) at
rows (0, 6, 11)) followed by a lower bidiagonal of 0-shifts, which is what makes the
back-substitution encoder below possible.

Encoder (back-substitution, no dense generator): the message blocks s_b stream through
(systematic output) while the twelve 27-bit row accumulators lambda_i = sum_b P(s_ib) s_b
build up — one constant rotation (pure wiring) per base-matrix entry, applied per completed
27-bit block. Then, because the column-12 shifts (1, 0, 1) telescope over the bidiagonal,
p0 = sum_i lambda_i, p1 = lambda_0 + P(1) p0 and p_{r+1} = p_r + lambda_r (+ p0 at r = 6);
row 11 closes by construction (H*c^T = 0 is verified against the expanded H in the tests).
Cost vs a dense generator: ~450 flops and a wire-selected XOR network instead of a
324x324-bit ROM and wide XOR trees — and the base-matrix structure stays legible.

Decoder (row-layered normalized min-sum, serial): one layer per base row (12 layers per
iteration); the 27 check rows of a layer touch disjoint variables, so they are processed
serially with no schedule hazard. Per check row: read the compressed old check message
(min1/min2/index/signs — the standard min-sum compression), then for each of the 7-8 edges
read APP, form Q = APP - R_old at full precision, feed |Q| clamped to 2**llr_bits - 1 into
the min1/min2/sign accumulation, and write back APP = sat(Q + R_new). Clamping Q *only* on
the check-node input (never in the APP update path) is essential: a clamped write-back
breaks the subtract/add consistency of layered decoding and diverges (measured: BER 3.7e-1
instead of 9.8e-3 at 2.0 dB). Normalization factor 0.75 is exact-by-construction:
norm(x) = x - (x >> 2). Early termination: each check row's on-the-fly syndrome (parity of
the Q signs); an iteration with every check satisfied stops the decode with ``parity_ok``.

Internal widths (derived from ``llr_bits``, default 4):

- APP:      llr_bits + 2 bits signed, saturated to ±(2**(llr_bits+1) - 1) = ±31.
- |Q| seen by the check node: llr_bits bits, clamped to 2**llr_bits - 1 = 15.
- Check messages: normalized magnitudes <= norm(15) = 12 (llr_bits bits) + sign.
- Q full precision: llr_bits + 3 bits signed (|APP| + |R| <= 31 + 12 = 43).
- APP update: Q + R <= 43 + 12 = 55 before saturation (llr_bits + 3 bits + saturate).

Quantized waterfall (4-bit LLRs = clip(round(4y), -7, 7), BPSK, AWGN, max_iters = 8,
NumPy model, 400-1200 blocks/point): BER 1.2e-1 @ 1.0 dB, 5.1e-2 @ 1.5 dB, 9.8e-3 @ 2.0 dB,
6.7e-4 @ 2.5 dB, < 2.6e-6 (0 errors) @ 3.0 dB Eb/N0.

Both blocks are block-serial and framed: boundaries are counted from reset (sink
``first``/``last`` ignored), outputs framed with ``first``/``last``. The LLR input is one
LLR per beat (a z-parallel QC datapath — 27 check rows per cycle — is the documented
follow-up); see ``cycles_per_block`` for the decode cost.
"""

from functools import reduce
from operator  import xor

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check

# 802.11n Base Matrix --------------------------------------------------------------------------------

# IEEE 802.11-2012 Annex F, Table F-1: n = 648, rate 1/2, z = 27. -1 = zero block, s >= 0 =
# identity right-cyclic-shifted by s (row r of the block has its one at column (r + s) mod z).
LDPC_BASE = [
    [ 0, -1, -1, -1,  0,  0, -1, -1,  0, -1, -1,  0,  1,  0, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
    [22,  0, -1, -1, 17, -1,  0,  0, 12, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1, -1, -1, -1],
    [ 6, -1,  0, -1, 10, -1, -1, -1, 24, -1,  0, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1, -1, -1],
    [ 2, -1, -1,  0, 20, -1, -1, -1, 25,  0, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1, -1],
    [23, -1, -1, -1,  3, -1, -1, -1,  0, -1,  9, 11, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1],
    [24, -1, 23,  1, 17, -1,  3, -1, 10, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1],
    [25, -1, -1, -1,  8, -1, -1, -1,  7, 18, -1, -1,  0, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1],
    [13, 24, -1, -1,  0, -1,  8, -1,  6, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1],
    [ 7, 20, -1, 16, 22, 10, -1, -1, 23, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1, -1],
    [11, -1, -1, -1, 19, -1, -1, -1, 13, -1,  3, 17, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1],
    [25, -1,  8, -1, 23, 18, -1, 14,  9, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0],
    [ 3, -1, -1, -1, 16, -1, -1,  2, 25,  5, -1, -1,  1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0],
]

LDPC_Z  = 27                 # Circulant (lifting) size.
LDPC_MB = len(LDPC_BASE)     # Base rows (12).
LDPC_NB = len(LDPC_BASE[0])  # Base columns (24).
LDPC_N  = LDPC_NB*LDPC_Z     # Codeword bits (648).
LDPC_K  = (LDPC_NB - LDPC_MB)*LDPC_Z  # Message bits (324).

def ldpc_layer_edges():
    """Per base row: the (col_block, shift) nonzero entries, in ascending column order.

    This *is* the decoder schedule: layer i processes its edges in this order, and check
    row j of layer i touches variable ``b*z + (s + j) % z`` for each edge (b, s).
    """
    return [[(b, s) for b, s in ((b, LDPC_BASE[i][b]) for b in range(LDPC_NB)) if s >= 0]
            for i in range(LDPC_MB)]

def _rot27(sig, s):
    """P(s) x as pure wiring: bit r of the result is bit (r + s) mod 27 of ``sig``."""
    s = s % LDPC_Z
    return sig if s == 0 else Cat(sig[s:], sig[:s])

# LDPC Encoder ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLDPCEncoder(LiteXModule):
    """802.11n rate-1/2 (648, 324) LDPC encoder: 324 message bits in, 648 codeword bits out.

    Back-substitution over the quasi-cyclic dual-diagonal parity structure (see the module
    docstring): message bits pass straight through (systematic) while the twelve 27-bit
    lambda accumulators collect one constant rotation per base-matrix entry at each completed
    message block; the parity chain is then solved one 27-bit block at a time, each at the
    drain boundary of the previous one (the lambda bank shifts down so the chain always taps
    its head — no replicated XOR chain, no 324-bit parity register). Message boundaries are
    counted from reset (sink ``first``/``last`` ignored); each output codeword is framed
    with ``first``/``last``.

    Parameters
    ----------
    with_csr : bool
        Add the configuration CSR (code dimensions).
    """
    def __init__(self, with_csr=True):
        z, mb = LDPC_Z, LDPC_MB
        self.n = LDPC_N
        self.k = LDPC_K
        self.z = z
        self.latency = None  # Variable rate (k bits in -> n bits out, framed).
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])

        # # #

        # Counters (shared by the datapath muxes below).
        # -----------------------------------------------
        t   = Signal(max=z)   # Bit position within the current block (message and drain).
        blk = Signal(max=mb)  # Message block 0..11.
        pb  = Signal(max=mb)  # Parity block being drained.

        # Lambda accumulators.
        # --------------------
        # lambda_i = sum_b P(s_ib) s_b, built one message block at a time: cur collects the
        # 27 bits of the current block (cur[t] = bit t), and on the block's last bit each
        # row with an entry XORs in the completed block's contribution. The contribution is
        # a wire-selected increment (rotations are pure wiring; the block counter only picks
        # which one — this keeps the per-bit logic a narrow select + XOR).
        cur  = Signal(z)
        lam  = [Signal(z, name=f"lam{i}") for i in range(mb)]
        full = Signal(z)  # The completed block: cur with the incoming bit at position 26.
        self.comb += full.eq(Cat(cur[1:], self.sink.data))
        inc  = [Signal(z, name=f"inc{i}") for i in range(mb)]
        for i in range(mb):
            self.comb += Case(blk, {b: inc[i].eq(_rot27(full, LDPC_BASE[i][b]))
                                    for b in range(mb) if LDPC_BASE[i][b] >= 0})
        lam_update = [NextValue(lam[i], lam[i] ^ inc[i]) for i in range(mb)]

        # Parity back-substitution (rolling).
        # -----------------------------------
        # p0 = sum_i lambda_i (the column-12 shifts (1, 0, 1) telescope to P(0) over the
        # bidiagonal); then p1 = lambda_0 + P(1) p0 and p_{r+1} = p_r + lambda_r (+ p0 at
        # r = 6, the middle column-12 entry); row 11 closes by construction. Instead of
        # solving all twelve blocks at once (which replicates the XOR chain per block), the
        # next block is computed at each drain boundary from the running accumulator and the
        # head of the lambda bank, which shifts down by one block per boundary.
        p0r    = Signal(z)  # p0 (kept for the r = 6 step).
        pacc   = Signal(z)  # Chain accumulator: p_pb at the start of drain block pb (seeded P(1) p0).
        pdrain = Signal(z)  # Shift-out copy of the block being drained.
        pnext  = Signal(z)  # p_{pb+1}, solved at the drain boundary of block pb.
        p0_x   = reduce(xor, lam)

        # FSM.
        # ----
        self.comb += [
            pnext.eq(pacc ^ lam[0]),
            If(pb == 6, pnext.eq(pacc ^ lam[0] ^ p0r)),  # p7 = p6 + lambda_6 + p0.
        ]
        self.fsm = fsm = FSM(reset_state="MESSAGE")
        fsm.act("MESSAGE",  # Pass the 324 message bits through while accumulating lambdas.
            self.sink.ready.eq(self.source.ready),
            self.source.valid.eq(self.sink.valid),
            self.source.data.eq(self.sink.data),
            self.source.first.eq((blk == 0) & (t == 0)),
            If(self.sink.valid & self.source.ready,
                NextValue(cur, full),
                If(t == (z - 1),
                    *lam_update,
                    NextValue(t, 0),
                    If(blk == (mb - 1),
                        NextValue(blk, 0),
                        NextState("CALC"),
                    ).Else(NextValue(blk, blk + 1)),
                ).Else(NextValue(t, t + 1)),
            )
        )
        fsm.act("CALC",  # p0 = XOR of the twelve lambda accumulators; seed the chain with P(1) p0.
            NextValue(p0r, p0_x),
            NextValue(pdrain, p0_x),
            NextValue(pacc, _rot27(p0_x, 1)),
            NextState("DRAIN"),
        )
        fsm.act("DRAIN",  # Drain parity block pb bit-serially; solve block pb+1 at the boundary.
            self.source.valid.eq(1),
            self.source.data.eq(pdrain[0]),
            self.source.last.eq((pb == (mb - 1)) & (t == (z - 1))),
            If(self.source.ready,
                If(t == (z - 1),
                    NextValue(t, 0),
                    If(pb == (mb - 1),
                        NextValue(pb, 0),
                        *[NextValue(l, 0) for l in lam],  # Ready for the next message.
                        NextState("MESSAGE"),
                    ).Else(
                        NextValue(pdrain, pnext),
                        NextValue(pacc, pnext),
                        *[NextValue(lam[i], lam[i + 1]) for i in range(mb - 1)],
                        NextValue(pb, pb + 1),
                    ),
                ).Else(
                    NextValue(pdrain, pdrain[1:]),
                    NextValue(t, t + 1),
                ),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n", size=10, description="Codeword length in bits."),
            CSRField("k", size=9,  description="Message length in bits."),
            CSRField("z", size=5,  description="Circulant (lifting) size."),
        ])
        self.comb += [
            self._config.fields.n.eq(self.n),
            self._config.fields.k.eq(self.k),
            self._config.fields.z.eq(self.z),
        ]

# LDPC Decoder ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLDPCDecoder(LiteXModule):
    """802.11n rate-1/2 (648, 324) LDPC decoder: 648 LLRs in, 324 corrected bits out.

    Row-layered normalized min-sum (factor 0.75 = x - (x >> 2)), one LLR per beat in
    (positive = bit 0 more likely, the :class:`~litedsp.comm.soft_demap.LiteDSPSoftDemapper`
    convention), hard-decision message bits out, framed. The 27 check rows of each layer are
    processed serially over a single-port APP RAM (n entries) with compressed check messages
    (min1/min2/index/signs) per check row; see the module docstring for the schedule, the
    internal widths and the measured waterfall. Early termination on an iteration whose
    on-the-fly syndrome (parity of the check-node input signs) is clean everywhere;
    ``iterations``/``parity_ok`` report the last block, ``failures`` counts blocks that
    exhausted ``max_iters`` unconverged (sticky count, ``clear`` resets it). Worst-case
    ``cycles_per_block`` = n + max_iters*z*(2E + 2m_b) + 2k + 4 (~44.5 kcycles at
    max_iters = 8; E = 88 edges) plus handshake stalls; early termination shortens it by
    ~5.4 kcycles per saved iteration. Block boundaries are counted from reset (sink
    ``first``/``last`` ignored).

    Parameters
    ----------
    llr_bits : int
        Signed input LLR width (>= 2; default 4). All internal widths derive from it
        (APP: llr_bits + 2 bits, check-node |Q| clamp: 2**llr_bits - 1).
    max_iters : int
        Decoding iteration budget per block (1..31; default 8).
    with_csr : bool
        Add the configuration/status CSRs.
    """
    def __init__(self, llr_bits=4, max_iters=8, with_csr=True):
        check(llr_bits >= 2, "expected llr_bits >= 2")
        check(1 <= max_iters <= 31, "expected max_iters in 1..31")
        z, mb   = LDPC_Z, LDPC_MB
        n, k    = LDPC_N, LDPC_K
        layers  = ldpc_layer_edges()
        degs    = [len(l) for l in layers]
        max_deg = max(degs)  # 8 for this code.
        qmax    = (1 << llr_bits) - 1        # Check-node |Q| clamp (15).
        appmax  = (1 << (llr_bits + 1)) - 1  # APP saturation (31).
        app_w   = llr_bits + 2               # APP width, signed.
        mag_w   = llr_bits                   # Check-message magnitude width (<= norm(qmax)).
        q_w     = llr_bits + 3               # Full-precision Q width, signed (<= appmax + norm(qmax)).
        idx_w   = bits_for(max_deg - 1)
        self.llr_bits  = llr_bits
        self.max_iters = max_iters
        self.n = n
        self.k = k
        self.z = z
        self.latency = None  # Variable (framed block decode; see cycles_per_block).
        # Worst-case decode cycles per block (load + max_iters full iterations + drain),
        # excluding handshake stalls; each check row costs 2*deg + 2 cycles.
        self.cycles_per_block = n + max_iters*z*sum(2*d + 2 for d in degs) + 2*k + 4
        self.sink   = stream.Endpoint([("llrs", llr_bits)])
        self.source = stream.Endpoint([("data", 1)])
        self.iterations = Signal(max=max_iters + 1)  # Iterations used by the last block.
        self.parity_ok  = Signal()                   # Last block converged (zero syndrome).
        self.failures   = Signal(16)                 # Unconverged blocks since clear.
        self.clear      = Signal()                   # Clear the failure counter.

        # # #

        # Edge ROM (constant mux arrays).
        # -------------------------------
        # Flat edge list in schedule order; per edge the target block's base address (b*z)
        # and shift. Per layer: degree and flat start index.
        flat     = [e for layer in layers for e in layer]
        starts   = [sum(degs[:i]) for i in range(mb)]
        col_base = Array(b*z for b, s in flat)
        shifts   = Array(s for b, s in flat)
        deg_arr  = Array(degs)
        start_arr = Array(starts)

        # Memories.
        # ---------
        # APP RAM: one signed llr_bits+2 value per codeword bit (single R/W port: the FSM
        # serializes load / row read / row write / drain). Check RAM: one compressed message
        # per check row: {min1n, min2n (normalized magnitudes), index of min1, Q signs}.
        chk_w   = 2*mag_w + idx_w + max_deg
        app_ram = Memory(app_w, n)
        chk_ram = Memory(chk_w, mb*z)
        app_p   = app_ram.get_port(write_capable=True)
        chk_p   = chk_ram.get_port(write_capable=True)
        self.specials += app_ram, chk_ram, app_p, chk_p

        # Sequencing state.
        # -----------------
        it      = Signal(max=max_iters + 1, reset=1)  # Iteration 1..max_iters.
        i       = Signal(max=mb)                      # Layer (base row).
        j       = Signal(max=z)                       # Check row within the layer.
        e       = Signal(max=max_deg + 1)             # Edge counter (read issue / write).
        row_idx = Signal(max=mb*z)                    # Flat check row index (chk RAM address).
        first_it = Signal(reset=1)                    # Iteration 1: old messages forced to 0.
        unsat    = Signal()                           # A check failed in this iteration.
        deg      = Signal(max=max_deg + 1)
        estart   = Signal(max=len(flat))
        self.comb += [deg.eq(deg_arr[i]), estart.eq(start_arr[i])]

        # Circulant addressing.
        # ---------------------
        # Edge g touches variable b*z + (s + j) mod z; (s + j) mod z as add + conditional
        # subtract. rd_g/wr_g select the read-issue edge (e) or write edge (e) — same
        # counter, different phases.
        g     = Signal(max=len(flat))
        sj    = Signal(max=2*z)
        vaddr = Signal(max=n)
        self.comb += [
            g.eq(estart + e),
            sj.eq(shifts[g] + j),
            vaddr.eq(col_base[g] + Mux(sj >= z, sj - z, sj)),
        ]

        # Old check message (expanded once at row start).
        # ------------------------------------------------
        # The RAM stores the compact {min1, min2, index, signs} representation. Expand its
        # eight edge messages into a small register file at the row boundary so the per-edge
        # APP update does not repeatedly traverse parity/index selection and sign restoration
        # before the min comparator. This is a latency-neutral row-level pipeline boundary.
        chk_m1    = Signal(mag_w)
        chk_m2    = Signal(mag_w)
        chk_idx   = Signal(idx_w)
        chk_signs = Signal(max_deg)
        chk_tot   = Signal()
        self.comb += [
            chk_m1.eq(chk_p.dat_r[0:mag_w]),
            chk_m2.eq(chk_p.dat_r[mag_w:2*mag_w]),
            chk_idx.eq(chk_p.dat_r[2*mag_w:2*mag_w + idx_w]),
            chk_signs.eq(chk_p.dat_r[2*mag_w + idx_w:]),
            chk_tot.eq(reduce(xor, [chk_signs[b] for b in range(max_deg)])),
        ]
        r_old_regs = Array(Signal((mag_w + 1, True), name=f"r_old{b}")
                           for b in range(max_deg))

        # Check-node accumulation (min1/min2/index/sign) over the row's edges.
        # --------------------------------------------------------------------
        e_d    = Signal(max=max_deg + 1)  # Edge whose APP data is being processed (= e - 1).
        m1     = Signal(mag_w)
        m2     = Signal(mag_w)
        idx    = Signal(idx_w)
        sgacc  = Signal(max_deg)
        tot    = Signal()
        self.comb += e_d.eq(e - 1)

        # R_old for edge e_d, selected from the row-expanded register file (all zero on the
        # first iteration, when check RAM has no message for this block yet).
        r_old     = Signal((mag_w + 1, True))
        self.comb += r_old.eq(r_old_regs[e_d])

        # Q = APP - R_old: full precision for the write-back; the check node sees |Q|
        # clamped to qmax (clamping the write-back path would break the layered
        # subtract/add consistency and diverge — see the module docstring).
        app_r  = Signal((app_w, True))
        q_full = Signal((q_w, True))
        q_abs  = Signal(q_w - 1)
        q_mag  = Signal(mag_w)
        q_sgn  = Signal()
        self.comb += [
            app_r.eq(app_p.dat_r),
            q_full.eq(app_r - r_old),
            q_sgn.eq(q_full < 0),
            q_abs.eq(Mux(q_sgn, -q_full, q_full)),
            q_mag.eq(Mux(q_abs > qmax, qmax, q_abs)),
        ]

        # Q register file (per-index write enables, RS-decoder style).
        q_regs = Array(Signal((q_w, True), name=f"q{b}") for b in range(max_deg))
        q_we   = Signal()
        self.sync += [
            *[If(q_we & (e_d == b), q_regs[b].eq(q_full)) for b in range(max_deg)],
            *[If(q_we & (e_d == b), sgacc[b].eq(q_sgn))   for b in range(max_deg)],
            If(q_we,
                tot.eq(tot ^ q_sgn),
                If(q_mag < m1,
                    m2.eq(m1),
                    m1.eq(q_mag),
                    idx.eq(e_d),
                ).Elif(q_mag < m2,
                    m2.eq(q_mag),
                ),
            ),
        ]

        # New check message + APP write-back.
        # -----------------------------------
        # Normalization 0.75 applied once, at store time: both the write-back R_new and the
        # next iteration's R_old reconstruction use the same normalized magnitudes.
        m1n    = Signal(mag_w)
        m2n    = Signal(mag_w)
        self.comb += [m1n.eq(m1 - (m1 >> 2)), m2n.eq(m2 - (m2 >> 2))]
        r_new_mag = Signal(mag_w)
        r_new_sgn = Signal()
        r_new     = Signal((mag_w + 1, True))
        app_sum   = Signal((q_w + 1, True))
        app_wdata = Signal((app_w, True))
        self.comb += [
            r_new_mag.eq(Mux(e == idx, m2n, m1n)),
            r_new_sgn.eq(tot ^ (sgacc >> e)[0]),
            r_new.eq(Mux(r_new_sgn, -r_new_mag, r_new_mag)),
            app_sum.eq(q_regs[e] + r_new),
            If(app_sum > appmax,
                app_wdata.eq(appmax),
            ).Elif(app_sum < -appmax,
                app_wdata.eq(-appmax),
            ).Else(
                app_wdata.eq(app_sum),
            ),
        ]

        # Status.
        # -------
        blk_ok   = Signal()  # Pulses: block converged (clean iteration syndrome),
        blk_fail = Signal()  #         block exhausted max_iters unconverged.
        self.sync += [
            If(blk_ok,
                self.parity_ok.eq(1),
                self.iterations.eq(it),
            ),
            If(blk_fail,
                self.parity_ok.eq(0),
                self.iterations.eq(max_iters),
                self.failures.eq(self.failures + 1),
            ),
            If(self.clear, self.failures.eq(0)),
        ]

        # FSM.
        # ----
        cnt      = Signal(max=n)  # Load / drain position.
        row_done = Signal()       # Last write cycle of the current check row.
        iter_end = Signal()       # ... of the last row of the iteration.
        self.comb += [
            row_done.eq(e == (deg - 1)),
            iter_end.eq(row_done & (i == (mb - 1)) & (j == (z - 1))),
        ]
        next_row = [
            NextValue(e, 0),
            NextValue(row_idx, row_idx + 1),
            If(j == (z - 1),
                NextValue(j, 0),
                NextValue(i, i + 1),
            ).Else(NextValue(j, j + 1)),
        ]
        self.fsm = fsm = FSM(reset_state="LOAD")
        fsm.act("LOAD",  # Fill the APP RAM with the n sign-extended input LLRs.
            self.sink.ready.eq(1),
            app_p.adr.eq(cnt),
            app_p.dat_w.eq(Cat(self.sink.llrs,
                               Replicate(self.sink.llrs[-1], app_w - llr_bits))),
            app_p.we.eq(self.sink.valid),
            If(self.sink.valid,
                If(cnt == (n - 1),
                    NextValue(cnt, 0),
                    NextState("ROW_INIT"),
                ).Else(NextValue(cnt, cnt + 1)),
            )
        )
        fsm.act("ROW_INIT",  # Issue the compressed-message read; clear the row accumulators.
            chk_p.adr.eq(row_idx),
            NextValue(m1, qmax),
            NextValue(m2, qmax),
            NextValue(idx, 0),
            NextValue(tot, 0),
            NextValue(sgacc, 0),
            NextValue(e, 0),
            NextState("ROW_READ"),
        )
        fsm.act("ROW_READ",  # Issue APP reads (edge e); process edge e-1's data in flight.
            chk_p.adr.eq(row_idx),
            app_p.adr.eq(vaddr),
            If(e == 0,  # Check-RAM data registered during ROW_INIT: expand the old message.
                *[NextValue(r_old_regs[b],
                    Mux(first_it, 0,
                        Mux(chk_tot ^ chk_signs[b],
                            -Mux(chk_idx == b, chk_m2, chk_m1),
                             Mux(chk_idx == b, chk_m2, chk_m1))))
                  for b in range(max_deg)],
            ).Else(
                q_we.eq(1),
            ),
            If(e == deg,  # All reads issued and processed (e = 1..deg processed e-1).
                NextValue(e, 0),
                NextState("ROW_WRITE"),
            ).Else(NextValue(e, e + 1)),
        )
        fsm.act("ROW_WRITE",  # Write back APP = sat(Q + R_new); store the compressed message.
            app_p.adr.eq(vaddr),
            app_p.dat_w.eq(app_wdata),
            app_p.we.eq(1),
            If(e == 0,
                chk_p.adr.eq(row_idx),
                chk_p.dat_w.eq(Cat(m1n, m2n, idx, sgacc)),
                chk_p.we.eq(1),
                If(tot, NextValue(unsat, 1)),  # On-the-fly syndrome for this row.
            ),
            If(row_done,
                If(iter_end,
                    NextValue(i, 0),
                    NextValue(j, 0),
                    NextValue(e, 0),
                    NextValue(row_idx, 0),
                    NextValue(first_it, 0),
                    If(~unsat & ~tot,  # unsat registers rows 0..last-1; tot covers this row.
                        blk_ok.eq(1),
                        NextState("OUT_READ"),
                    ).Elif(it == max_iters,
                        blk_fail.eq(1),
                        NextState("OUT_READ"),
                    ).Else(
                        NextValue(it, it + 1),
                        NextValue(unsat, 0),
                        NextState("ROW_INIT"),
                    ),
                ).Else(
                    *next_row,
                    NextState("ROW_INIT"),
                ),
            ).Else(NextValue(e, e + 1)),
        )
        fsm.act("OUT_READ",  # Issue the APP read of message bit cnt.
            app_p.adr.eq(cnt),
            NextState("OUT_EMIT"),
        )
        fsm.act("OUT_EMIT",  # Hard decision: APP < 0 -> bit 1 (positive LLR = bit 0).
            app_p.adr.eq(cnt),
            self.source.valid.eq(1),
            self.source.data.eq(app_p.dat_r[app_w - 1]),
            self.source.first.eq(cnt == 0),
            self.source.last.eq(cnt == (k - 1)),
            If(self.source.ready,
                If(cnt == (k - 1),
                    NextValue(cnt, 0),
                    NextValue(it, 1),
                    NextValue(first_it, 1),
                    NextValue(unsat, 0),
                    NextState("LOAD"),
                ).Else(NextValue(cnt, cnt + 1), NextState("OUT_READ")),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n",         size=10, description="Codeword length in bits."),
            CSRField("k",         size=9,  description="Message length in bits."),
            CSRField("llr_bits",  size=4,  description="Signed input LLR width."),
            CSRField("max_iters", size=5,  description="Iteration budget per block."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("iterations", size=5, description="Iterations used by the last decoded block."),
            CSRField("parity_ok",  size=1, description="Last block converged to a zero syndrome."),
        ])
        self._failures = CSRStatus(16, description="Blocks that exhausted max_iters unconverged since clear.")
        self._clear    = CSRStorage(1,  description="Clear the failure counter (write to clear).")
        self.comb += [
            self._config.fields.n.eq(self.n),
            self._config.fields.k.eq(self.k),
            self._config.fields.llr_bits.eq(self.llr_bits),
            self._config.fields.max_iters.eq(self.max_iters),
            self._status.fields.iterations.eq(self.iterations),
            self._status.fields.parity_ok.eq(self.parity_ok),
            self._failures.status.eq(self.failures),
            self.clear.eq(self._clear.re),
        ]
