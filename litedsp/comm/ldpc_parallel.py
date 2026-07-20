#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Z-parallel decoder for the 802.11n (648, 324) quasi-cyclic LDPC code.

The serial decoder in :mod:`litedsp.comm.ldpc` minimizes area by processing one of the 27
lifted check rows at a time. This architecture processes all ``z=27`` rows of a base-matrix
layer together. It retains the same row-layered normalized min-sum arithmetic and compressed
check messages, but stores APP values as 24 vectors and check state as 12 vectors. Each edge
passes through read, lane-local Q, check-update, and write stages; the external stream remains
one LLR/bit per beat.
"""

from functools import reduce
from operator  import xor

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common    import check
from litedsp.comm.ldpc import (LDPC_Z, LDPC_MB, LDPC_NB, LDPC_N, LDPC_K,
                               ldpc_layer_edges)


@ResetInserter()
class LiteDSPLDPCDecoderZParallel(LiteXModule):
    """27-row-parallel normalized min-sum LDPC decoder.

    The algorithm and quantization are bit-exact with :class:`LiteDSPLDPCDecoder`; the trade-off
    is replicated check-node arithmetic and wider vector memories in exchange for removing the
    factor ``z`` from the per-iteration schedule. With the default code, an iteration takes
    ``4*E + m_b = 364`` clocks instead of ``z*(2*E + 2*m_b) = 5400`` clocks in the serial core.
    Load and output remain bit-serial, so worst-case ``cycles_per_block`` is 3908 clocks at eight
    iterations, excluding handshake stalls (versus 44,500 for the serial architecture).

    The characterized default reaches 57.9/90.4/139.7 MHz on ECP5/Artix-7/Artix UltraScale+,
    or 14.8/23.1/35.7 thousand worst-case blocks/s. That is 6.4--8.3x the serial core's
    family-matched block throughput, at 13--21x its LUT count and about 13--14x its register
    count (Artix-7 also uses 10 BRAM tiles rather than one). The 100 MHz engineering target is
    closed on UltraScale+ only, so implementation sweeps classify this wide datapath as a
    capacity/timing stress configuration rather than a compact drop-in replacement.

    Parameters
    ----------
    llr_bits : int
        Signed input LLR width (>= 2; default 4).
    max_iters : int
        Decoding iteration budget per block (1..31; default 8).
    with_csr : bool
        Add configuration/status CSRs.
    """
    def __init__(self, llr_bits=4, max_iters=8, with_csr=True):
        check(llr_bits >= 2, "expected llr_bits >= 2")
        check(1 <= max_iters <= 31, "expected max_iters in 1..31")
        z, mb, nb = LDPC_Z, LDPC_MB, LDPC_NB
        n, k = LDPC_N, LDPC_K
        layers  = ldpc_layer_edges()
        degs    = [len(layer) for layer in layers]
        max_deg = max(degs)
        flat     = [edge for layer in layers for edge in layer]
        starts   = [sum(degs[:i]) for i in range(mb)]

        qmax   = (1 << llr_bits) - 1
        appmax = (1 << (llr_bits + 1)) - 1
        app_w  = llr_bits + 2
        mag_w  = llr_bits
        q_w    = llr_bits + 3
        idx_w  = bits_for(max_deg - 1)
        chk_w  = 2*mag_w + idx_w + max_deg

        self.llr_bits  = llr_bits
        self.max_iters = max_iters
        self.n = n
        self.k = k
        self.z = z
        self.parallelism = z
        self.latency = None
        self.cycles_per_iteration = 4*sum(degs) + mb
        self.cycles_per_block = (n + max_iters*self.cycles_per_iteration +
            k + 2*(k//z))
        self.sink   = stream.Endpoint([("llrs", llr_bits)])
        self.source = stream.Endpoint([("data", 1)])
        self.iterations = Signal(max=max_iters + 1)
        self.parity_ok  = Signal()
        self.failures   = Signal(16)
        self.clear      = Signal()

        # # #

        # Schedule constants.
        col_blocks = Array(b for b, s in flat)
        shifts     = Array(s for b, s in flat)
        deg_arr    = Array(degs)
        start_arr  = Array(starts)

        # Vector memories: one APP word per variable block and one check-state word per layer.
        app_ram = Memory(z*app_w, nb)
        chk_ram = Memory(z*chk_w, mb)
        app_p   = app_ram.get_port(write_capable=True)
        chk_p   = chk_ram.get_port(write_capable=True)
        self.specials += app_ram, chk_ram, app_p, chk_p

        layer = Signal(max=mb)
        edge  = Signal(max=max_deg + 1)
        deg   = Signal(max=max_deg + 1)
        start = Signal(max=len(flat))
        g     = Signal(max=len(flat))
        shift = Signal(max=z)
        block = Signal(max=nb)
        self.comb += [
            deg.eq(deg_arr[layer]),
            start.eq(start_arr[layer]),
            g.eq(start + edge),
            shift.eq(shifts[g]),
            block.eq(col_blocks[g]),
        ]

        # Decode state.
        it       = Signal(max=max_iters + 1, reset=1)
        first_it = Signal(reset=1)
        unsat    = Signal()
        m1       = [Signal(mag_w, reset=qmax, name=f"m1_{j}") for j in range(z)]
        m2       = [Signal(mag_w, reset=qmax, name=f"m2_{j}") for j in range(z)]
        min_idx  = [Signal(idx_w, name=f"min_idx_{j}") for j in range(z)]
        signs    = [Signal(max_deg, name=f"signs_{j}") for j in range(z)]
        totals   = [Signal(name=f"total_{j}") for j in range(z)]
        q_regs   = [[Signal((q_w, True), name=f"q_{e}_{j}") for j in range(z)]
                    for e in range(max_deg)]

        # Check-state vector expansion.
        old_m1, old_m2 = [], []
        old_idx, old_signs, old_total = [], [], []
        for j in range(z):
            base = j*chk_w
            om1 = Signal(mag_w)
            om2 = Signal(mag_w)
            oi  = Signal(idx_w)
            os  = Signal(max_deg)
            ot  = Signal()
            self.comb += [
                om1.eq(chk_p.dat_r[base:base + mag_w]),
                om2.eq(chk_p.dat_r[base + mag_w:base + 2*mag_w]),
                oi.eq(chk_p.dat_r[base + 2*mag_w:base + 2*mag_w + idx_w]),
                os.eq(chk_p.dat_r[base + 2*mag_w + idx_w:base + chk_w]),
                ot.eq(reduce(xor, [os[b] for b in range(max_deg)])),
            ]
            old_m1.append(om1)
            old_m2.append(om2)
            old_idx.append(oi)
            old_signs.append(os)
            old_total.append(ot)

        # Rotate the selected APP block into check-row order and form all 27 Q values.
        app_lanes = Array(Signal((app_w, True), name=f"app_lane_{v}") for v in range(z))
        for v in range(z):
            self.comb += app_lanes[v].eq(app_p.dat_r[v*app_w:(v + 1)*app_w])
        rot_sum = [Signal(max=2*z, name=f"rot_sum_{j}") for j in range(z)]
        rot_idx = [Signal(max=z, name=f"rot_idx_{j}") for j in range(z)]
        app_rot = [Signal((app_w, True), name=f"app_rot_{j}") for j in range(z)]
        r_old   = [Signal((mag_w + 1, True), name=f"r_old_{j}") for j in range(z)]
        q_full  = [Signal((q_w, True), name=f"q_full_{j}") for j in range(z)]
        q_abs   = [Signal(q_w - 1, name=f"q_abs_{j}") for j in range(z)]
        q_mag   = [Signal(mag_w, name=f"q_mag_{j}") for j in range(z)]
        q_sign  = [Signal(name=f"q_sign_{j}") for j in range(z)]
        q_pipe  = [Signal((q_w, True), name=f"q_pipe_{j}") for j in range(z)]
        qmag_pipe = [Signal(mag_w, name=f"qmag_pipe_{j}") for j in range(z)]
        qsign_pipe = [Signal(name=f"qsign_pipe_{j}") for j in range(z)]
        for j in range(z):
            old_mag = Signal(mag_w)
            old_sgn = Signal()
            self.comb += [
                # Keep the pre-modulo sum explicitly six bits wide. Without this boundary,
                # Verilog expression sizing truncates ``shift + j`` at five bits for j >= 5,
                # while Migen simulation retains the carry.
                rot_sum[j].eq(shift + j),
                rot_idx[j].eq(Mux(rot_sum[j] >= z, rot_sum[j] - z, rot_sum[j])),
                app_rot[j].eq(app_lanes[rot_idx[j]]),
                old_mag.eq(Mux(old_idx[j] == edge, old_m2[j], old_m1[j])),
                old_sgn.eq(old_total[j] ^ (old_signs[j] >> edge)[0]),
                r_old[j].eq(Mux(first_it, 0, Mux(old_sgn, -old_mag, old_mag))),
                q_full[j].eq(app_rot[j] - r_old[j]),
                q_sign[j].eq(q_full[j] < 0),
                q_abs[j].eq(Mux(q_sign[j], -q_full[j], q_full[j])),
                q_mag[j].eq(Mux(q_abs[j] > qmax, qmax, q_abs[j])),
            ]

        # READ_PROCESS writes one edge vector and updates 27 independent check accumulators.
        q_we = Signal()
        for b in range(max_deg):
            for j in range(z):
                self.sync += If(q_we & (edge == b), q_regs[b][j].eq(q_pipe[j]))
        for j in range(z):
            self.sync += If(q_we,
                totals[j].eq(totals[j] ^ qsign_pipe[j]),
                *[If(edge == b, signs[j][b].eq(qsign_pipe[j])) for b in range(max_deg)],
                If(qmag_pipe[j] < m1[j],
                    m2[j].eq(m1[j]), m1[j].eq(qmag_pipe[j]), min_idx[j].eq(edge),
                ).Elif(qmag_pipe[j] < m2[j],
                    m2[j].eq(qmag_pipe[j]),
                ),
            )

        # Build one updated APP block in variable order for the WRITE pass.
        updated = Array(Signal((app_w, True), name=f"updated_{j}") for j in range(z))
        inv_idx = [Signal(max=z, name=f"inv_idx_{v}") for v in range(z)]
        write_lanes = [Signal((app_w, True), name=f"write_lane_{v}") for v in range(z)]
        packed_checks = []
        for j in range(z):
            m1n = Signal(mag_w)
            m2n = Signal(mag_w)
            rmag = Signal(mag_w)
            rsgn = Signal()
            rnew = Signal((mag_w + 1, True))
            qsel = Signal((q_w, True))
            asum = Signal((q_w + 1, True))
            self.comb += [
                m1n.eq(m1[j] - (m1[j] >> 2)),
                m2n.eq(m2[j] - (m2[j] >> 2)),
                rmag.eq(Mux(edge == min_idx[j], m2n, m1n)),
                rsgn.eq(totals[j] ^ (signs[j] >> edge)[0]),
                rnew.eq(Mux(rsgn, -rmag, rmag)),
                qsel.eq(Array([q_regs[b][j] for b in range(max_deg)])[edge]),
                asum.eq(qsel + rnew),
                If(asum > appmax,
                    updated[j].eq(appmax),
                ).Elif(asum < -appmax,
                    updated[j].eq(-appmax),
                ).Else(
                    updated[j].eq(asum),
                ),
            ]
            packed_checks.append(Cat(m1n, m2n, min_idx[j], signs[j]))
        for v in range(z):
            self.comb += [
                inv_idx[v].eq(Mux(v < shift, v + z - shift, v - shift)),
                write_lanes[v].eq(updated[inv_idx[v]]),
            ]
        app_write_word = Cat(*write_lanes)
        chk_write_word = Cat(*packed_checks)
        totals_any = Signal()
        self.comb += totals_any.eq(Cat(*totals) != 0)

        # Status pulses.
        blk_ok, blk_fail = Signal(), Signal()
        self.sync += [
            If(blk_ok,
                self.parity_ok.eq(1), self.iterations.eq(it),
            ),
            If(blk_fail,
                self.parity_ok.eq(0), self.iterations.eq(max_iters),
                self.failures.eq(self.failures + 1),
            ),
            If(self.clear, self.failures.eq(0)),
        ]

        # Bit-serial load packs 27 LLRs into one APP vector word.
        load_t   = Signal(max=z)
        load_blk = Signal(max=nb)
        load_vec = Signal(z*app_w)
        llr_ext  = Signal((app_w, True))
        load_full = Signal(z*app_w)
        self.comb += [
            llr_ext.eq(Cat(self.sink.llrs,
                Replicate(self.sink.llrs[-1], app_w - llr_bits))),
            load_full.eq(Cat(load_vec[app_w:], llr_ext)),
        ]

        # Message drain reads one APP vector then emits its 27 hard decisions.
        out_blk = Signal(max=mb)
        out_t   = Signal(max=z)
        out_vec = Signal(z*app_w)

        self.fsm = fsm = FSM(reset_state="LOAD")
        fsm.act("LOAD",
            self.sink.ready.eq(1),
            app_p.adr.eq(load_blk),
            app_p.dat_w.eq(load_full),
            app_p.we.eq(self.sink.valid & (load_t == (z - 1))),
            If(self.sink.valid,
                NextValue(load_vec, load_full),
                If(load_t == (z - 1),
                    NextValue(load_t, 0),
                    If(load_blk == (nb - 1),
                        NextValue(load_blk, 0),
                        NextValue(layer, 0), NextValue(edge, 0),
                        NextState("LAYER_INIT"),
                    ).Else(NextValue(load_blk, load_blk + 1)),
                ).Else(NextValue(load_t, load_t + 1)),
            ),
        )
        fsm.act("LAYER_INIT",
            chk_p.adr.eq(layer),
            *[NextValue(m1[j], qmax) for j in range(z)],
            *[NextValue(m2[j], qmax) for j in range(z)],
            *[NextValue(min_idx[j], 0) for j in range(z)],
            *[NextValue(signs[j], 0) for j in range(z)],
            *[NextValue(totals[j], 0) for j in range(z)],
            NextValue(edge, 0),
            NextState("READ_ISSUE"),
        )
        fsm.act("READ_ISSUE",
            chk_p.adr.eq(layer),
            app_p.adr.eq(block),
            NextState("Q_CAPTURE"),
        )
        # Capture the APP/check subtraction and magnitude clamp before the min1/min2 update.
        # Besides shortening the logic path, these lane-local registers break the long route
        # from the 162-bit APP memory output to all 27 replicated check accumulators.
        fsm.act("Q_CAPTURE",
            chk_p.adr.eq(layer),
            app_p.adr.eq(block),
            *[NextValue(q_pipe[j], q_full[j]) for j in range(z)],
            *[NextValue(qmag_pipe[j], q_mag[j]) for j in range(z)],
            *[NextValue(qsign_pipe[j], q_sign[j]) for j in range(z)],
            NextState("READ_PROCESS"),
        )
        fsm.act("READ_PROCESS",
            chk_p.adr.eq(layer),
            app_p.adr.eq(block),
            q_we.eq(1),
            If(edge == (deg - 1),
                NextValue(edge, 0),
                NextState("WRITE"),
            ).Else(
                NextValue(edge, edge + 1),
                NextState("READ_ISSUE"),
            ),
        )
        fsm.act("WRITE",
            app_p.adr.eq(block),
            app_p.dat_w.eq(app_write_word),
            app_p.we.eq(1),
            If(edge == 0,
                chk_p.adr.eq(layer),
                chk_p.dat_w.eq(chk_write_word),
                chk_p.we.eq(1),
                If(totals_any, NextValue(unsat, 1)),
            ),
            If(edge == (deg - 1),
                NextValue(edge, 0),
                If(layer == (mb - 1),
                    NextValue(layer, 0),
                    NextValue(first_it, 0),
                    If(~unsat & ~totals_any,
                        blk_ok.eq(1),
                        NextValue(out_blk, 0),
                        NextState("OUT_READ"),
                    ).Elif(it == max_iters,
                        blk_fail.eq(1),
                        NextValue(out_blk, 0),
                        NextState("OUT_READ"),
                    ).Else(
                        NextValue(it, it + 1),
                        NextValue(unsat, 0),
                        NextState("LAYER_INIT"),
                    ),
                ).Else(
                    NextValue(layer, layer + 1),
                    NextState("LAYER_INIT"),
                ),
            ).Else(NextValue(edge, edge + 1)),
        )
        fsm.act("OUT_READ",
            app_p.adr.eq(out_blk),
            NextState("OUT_CAPTURE"),
        )
        fsm.act("OUT_CAPTURE",
            app_p.adr.eq(out_blk),
            NextValue(out_vec, app_p.dat_r),
            NextValue(out_t, 0),
            NextState("OUT_EMIT"),
        )
        fsm.act("OUT_EMIT",
            self.source.valid.eq(1),
            self.source.data.eq(out_vec[app_w - 1]),
            self.source.first.eq((out_blk == 0) & (out_t == 0)),
            self.source.last.eq((out_blk == (mb - 1)) & (out_t == (z - 1))),
            If(self.source.ready,
                If(out_t == (z - 1),
                    NextValue(out_t, 0),
                    If(out_blk == (mb - 1),
                        NextValue(out_blk, 0),
                        NextValue(it, 1),
                        NextValue(first_it, 1),
                        NextValue(unsat, 0),
                        NextState("LOAD"),
                    ).Else(
                        NextValue(out_blk, out_blk + 1),
                        NextState("OUT_READ"),
                    ),
                ).Else(
                    NextValue(out_vec, Cat(out_vec[app_w:], C(0, app_w))),
                    NextValue(out_t, out_t + 1),
                ),
            ),
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n",         size=10, description="Codeword length in bits."),
            CSRField("k",         size=9,  description="Message length in bits."),
            CSRField("llr_bits",  size=4,  description="Signed input LLR width."),
            CSRField("max_iters", size=5,  description="Iteration budget per block."),
        ])
        self._architecture = CSRStatus(fields=[
            CSRField("parallelism", size=5, description="Lifted check rows processed together."),
            CSRField("cycles_per_iteration", size=10,
                description="Fixed clocks per full layered iteration."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("iterations", size=5, description="Iterations used by the last decoded block."),
            CSRField("parity_ok",  size=1, description="Last block converged to a zero syndrome."),
        ])
        self._failures = CSRStatus(16,
            description="Blocks that exhausted max_iters unconverged since clear.")
        self._clear = CSRStorage(1,
            description="Clear the failure counter (write to clear).")
        self.comb += [
            self._config.fields.n.eq(self.n),
            self._config.fields.k.eq(self.k),
            self._config.fields.llr_bits.eq(self.llr_bits),
            self._config.fields.max_iters.eq(self.max_iters),
            self._architecture.fields.parallelism.eq(self.parallelism),
            self._architecture.fields.cycles_per_iteration.eq(self.cycles_per_iteration),
            self._status.fields.iterations.eq(self.iterations),
            self._status.fields.parity_ok.eq(self.parity_ok),
            self._failures.status.eq(self.failures),
            self.clear.eq(self._clear.re),
        ]
