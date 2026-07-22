#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Z-parallel decoder for the 802.11n (648, 324) quasi-cyclic LDPC code.

The serial decoder in :mod:`litedsp.comm.ldpc` minimizes area by processing one of the 27
lifted check rows at a time. This architecture processes all ``z=27`` rows of a base-matrix
layer together. It retains the same row-layered normalized min-sum arithmetic and compressed
check messages, but stores APP values and check state in one narrow bank per lifted row. Each
edge passes through bank read, cyclic rotation/Q, check-update, and write stages; the external
stream remains one LLR/bit per beat.
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
    is replicated check-node arithmetic and lane-banked state in exchange for removing the
    factor ``z`` from the per-iteration schedule. With the default code, an iteration takes
    ``5*E + 2*m_b = 464`` clocks instead of ``z*(2*E + 2*m_b) = 5400`` clocks in the serial core.
    Load and output remain bit-serial, so worst-case ``cycles_per_block`` is 4708 clocks at eight
    iterations, excluding handshake stalls (versus 44,500 for the serial architecture).

    The characterized default reaches 74.7/102.4/151.2 MHz on ECP5/Artix-7/Artix UltraScale+,
    or 15.9/21.8/32.1 thousand worst-case blocks/s. That is 6.3--7.8x the serial core's
    family-matched block throughput, at 10--12x its LUT count and about 15--18x its register
    count. The 100 MHz engineering target closes on both Xilinx profiles; ECP5 remains open,
    so implementation sweeps retain this wide datapath as a capacity/timing stress
    configuration rather than a compact drop-in replacement.

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
        self.cycles_per_iteration = 5*sum(degs) + 2*mb
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

        # Lane-banked state. The previous 162-bit APP and 540-bit check words inferred wide
        # muxes (and family-dependent BRAM packing) whose routes dominated the clock period.
        # All banks share an address and are read/written together, preserving the algorithm
        # while giving implementation tools 27 independent narrow memories to place.
        app_rams = [Memory(app_w, nb, name=f"app_ram_{j}") for j in range(z)]
        chk_rams = [Memory(chk_w, mb, name=f"chk_ram_{j}") for j in range(z)]
        app_ps   = [ram.get_port(write_capable=True) for ram in app_rams]
        chk_ps   = [ram.get_port(write_capable=True) for ram in chk_rams]
        self.specials += app_rams + chk_rams + app_ps + chk_ps

        layer = Signal(max=mb)
        edge  = Signal(max=max_deg + 1)
        deg   = Signal(max=max_deg + 1)
        start = Signal(max=len(flat))
        g     = Signal(max=len(flat))
        shift = Signal(max=z)
        block = Signal(max=nb)
        write_edge  = Signal(max=max_deg + 1)
        write_g     = Signal(max=len(flat))
        write_shift = Signal(max=z)
        write_block = Signal(max=nb)
        self.comb += [
            deg.eq(deg_arr[layer]),
            start.eq(start_arr[layer]),
            g.eq(start + edge),
            shift.eq(shifts[g]),
            block.eq(col_blocks[g]),
            write_g.eq(start + write_edge),
            write_shift.eq(shifts[write_g]),
            write_block.eq(col_blocks[write_g]),
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
            om1 = Signal(mag_w)
            om2 = Signal(mag_w)
            oi  = Signal(idx_w)
            os  = Signal(max_deg)
            ot  = Signal()
            self.comb += [
                om1.eq(chk_ps[j].dat_r[:mag_w]),
                om2.eq(chk_ps[j].dat_r[mag_w:2*mag_w]),
                oi.eq(chk_ps[j].dat_r[2*mag_w:2*mag_w + idx_w]),
                os.eq(chk_ps[j].dat_r[2*mag_w + idx_w:]),
                ot.eq(reduce(xor, [os[b] for b in range(max_deg)])),
            ]
            old_m1.append(om1)
            old_m2.append(om2)
            old_idx.append(oi)
            old_signs.append(os)
            old_total.append(ot)

        # Rotate the selected APP block into check-row order with a logarithmic cyclic barrel
        # network. A flat Array indexed independently by every lane synthesized as 27 unrelated
        # 27:1 muxes; the five shared binary rotation levels express the QC structure directly.
        rot_stages = [[p.dat_r for p in app_ps]]
        for bit, amount in enumerate((1, 2, 4, 8, 16)):
            stage_lanes = [Signal((app_w, True), name=f"app_rot_{bit}_{j}") for j in range(z)]
            for j in range(z):
                self.comb += stage_lanes[j].eq(Mux(
                    shift[bit], rot_stages[-1][(j + amount) % z], rot_stages[-1][j]))
            rot_stages.append(stage_lanes)
        rotated_app = rot_stages[-1]
        app_rot = [Signal((app_w, True), name=f"app_rot_pipe_{j}") for j in range(z)]

        # Form all 27 lane-local Q values.
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
        updated = [Signal((app_w, True), name=f"updated_{j}") for j in range(z)]
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
                rmag.eq(Mux(write_edge == min_idx[j], m2n, m1n)),
                rsgn.eq(totals[j] ^ (signs[j] >> write_edge)[0]),
                rnew.eq(Mux(rsgn, -rmag, rmag)),
                qsel.eq(Array([q_regs[b][j] for b in range(max_deg)])[write_edge]),
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

        # Return from check-row order to variable order with the inverse cyclic barrel network.
        inv_stages = [updated]
        for bit, amount in enumerate((1, 2, 4, 8, 16)):
            stage_lanes = [Signal((app_w, True), name=f"app_inv_{bit}_{j}") for j in range(z)]
            for j in range(z):
                self.comb += stage_lanes[j].eq(Mux(
                    write_shift[bit], inv_stages[-1][(j - amount) % z], inv_stages[-1][j]))
            inv_stages.append(stage_lanes)
        write_lanes = inv_stages[-1]
        write_pipe = [Signal((app_w, True), name=f"app_write_pipe_{j}") for j in range(z)]
        write_block_pipe = Signal(max=nb)
        # The pipe advances continuously. WRITE consumes the value captured on the preceding
        # clock while the look-ahead network prepares the next edge; unconditional registers
        # avoid a high-fanout clock-enable mux across all 27 lanes.
        self.sync += [write_pipe[j].eq(write_lanes[j]) for j in range(z)]
        self.sync += write_block_pipe.eq(write_block)
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
            *[app_ps[j].adr.eq(load_blk) for j in range(z)],
            *[app_ps[j].dat_w.eq(load_full[j*app_w:(j + 1)*app_w]) for j in range(z)],
            *[app_ps[j].we.eq(self.sink.valid & (load_t == (z - 1))) for j in range(z)],
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
            *[p.adr.eq(layer) for p in chk_ps],
            *[NextValue(m1[j], qmax) for j in range(z)],
            *[NextValue(m2[j], qmax) for j in range(z)],
            *[NextValue(min_idx[j], 0) for j in range(z)],
            *[NextValue(signs[j], 0) for j in range(z)],
            *[NextValue(totals[j], 0) for j in range(z)],
            NextValue(edge, 0),
            NextState("READ_ISSUE"),
        )
        fsm.act("READ_ISSUE",
            *[p.adr.eq(layer) for p in chk_ps],
            *[p.adr.eq(block) for p in app_ps],
            NextState("APP_CAPTURE"),
        )
        fsm.act("APP_CAPTURE",
            *[p.adr.eq(layer) for p in chk_ps],
            *[p.adr.eq(block) for p in app_ps],
            *[NextValue(app_rot[j], rotated_app[j]) for j in range(z)],
            NextState("Q_CAPTURE"),
        )
        # Capture the APP/check subtraction and magnitude clamp before the min1/min2 update.
        # These lane-local registers make the minimum recurrence the third and final edge stage.
        fsm.act("Q_CAPTURE",
            *[p.adr.eq(layer) for p in chk_ps],
            *[p.adr.eq(block) for p in app_ps],
            *[NextValue(q_pipe[j], q_full[j]) for j in range(z)],
            *[NextValue(qmag_pipe[j], q_mag[j]) for j in range(z)],
            *[NextValue(qsign_pipe[j], q_sign[j]) for j in range(z)],
            NextState("READ_PROCESS"),
        )
        fsm.act("READ_PROCESS",
            *[p.adr.eq(layer) for p in chk_ps],
            *[p.adr.eq(block) for p in app_ps],
            q_we.eq(1),
            If(edge == (deg - 1),
                NextValue(edge, 0),
                NextValue(write_edge, 0),
                NextState("WRITE_CAPTURE"),
            ).Else(
                NextValue(edge, edge + 1),
                NextState("READ_ISSUE"),
            ),
        )
        # Fill the overlapped write pipe once per layer before committing one edge each clock.
        # This removes the previous min/select/rotation-to-RAM path at a 12-clock/iteration cost.
        fsm.act("WRITE_CAPTURE",
            NextValue(write_edge, 1),
            NextState("WRITE"),
        )
        fsm.act("WRITE",
            *[app_ps[j].adr.eq(write_block_pipe) for j in range(z)],
            *[app_ps[j].dat_w.eq(write_pipe[j]) for j in range(z)],
            *[app_ps[j].we.eq(1) for j in range(z)],
            If(edge == 0,
                *[chk_ps[j].adr.eq(layer) for j in range(z)],
                *[chk_ps[j].dat_w.eq(packed_checks[j]) for j in range(z)],
                *[chk_ps[j].we.eq(1) for j in range(z)],
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
            ).Else(
                NextValue(edge, edge + 1),
                If(edge < (deg - 2), NextValue(write_edge, write_edge + 1)),
            ),
        )
        fsm.act("OUT_READ",
            *[p.adr.eq(out_blk) for p in app_ps],
            NextState("OUT_CAPTURE"),
        )
        fsm.act("OUT_CAPTURE",
            *[p.adr.eq(out_blk) for p in app_ps],
            NextValue(out_vec, Cat(*[p.dat_r for p in app_ps])),
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
