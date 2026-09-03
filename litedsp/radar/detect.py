#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Detection post-processing: peak extraction with sub-bin interpolation, target lists."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourcePulse
from litex.soc.interconnect                  import stream

from litedsp.common import check, cell_layout, target_layout

# Peak Extractor -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPeakExtractor(LiteXModule):
    """Detected cells to sparse target records with sub-bin centroids.

    Consumes a CFAR map (``n_range_bins`` rows of ``n_doppler_bins`` cells on
    :func:`~litedsp.common.cell_layout`, rows counted from reset) through two line buffers so
    each cell is seen with its 3x3 neighbourhood (zero padded). A detected cell becomes a
    record when ``local_max`` is clear, or when it is a strict maximum over its raster-earlier
    neighbours and no smaller than the later ones (a plateau yields exactly one record). With
    ``interpolate`` the parabolic sub-bin offset along each axis,
    ``(y_next - y_prev) / (2 * (2 y0 - y_prev - y_next))`` in Q.frac_bits, is computed by a
    bit-serial divider (``frac_bits + 3`` cycles per record, the input is stalled), clamped to
    +/-0.5 bin (0 when the curvature is not negative). Output on
    :func:`~litedsp.common.target_layout`: one burst per CPI, records (``hit = 1``, ``range`` and
    ``doppler`` unsigned Q.frac_bits, ``data`` = the peak cell) closed by a terminator beat
    (``hit = 0``, ``data`` = record count, ``last``); the optional ``ev.cpi`` interrupt fires with
    the terminator. A misplaced ``first``/``last`` sets the sticky ``frame_error``.
    ``latency = None``; rate data dependent (one virtual cell per row and one virtual row per
    CPI are flushed with ``sink.ready`` low).
    """
    def __init__(self, n_range_bins=64, n_doppler_bins=16, data_width=17, index_width=12, frac_bits=4,
        with_csr=True, with_irq=False):
        check(n_range_bins >= 2 and n_doppler_bins >= 2, "expected n_range_bins, n_doppler_bins >= 2")
        check(1 <= frac_bits <= 8, "expected 1 <= frac_bits <= 8")
        check(2**index_width >= max(n_range_bins, n_doppler_bins), "expected index_width to hold the bin indexes")
        self.n_range_bins   = n_range_bins
        self.n_doppler_bins = n_doppler_bins
        self.data_width     = data_width
        self.index_width    = index_width
        self.frac_bits      = frac_bits
        self.latency        = None
        self.sink   = stream.Endpoint(cell_layout(data_width))
        self.source = stream.Endpoint(target_layout(data_width, index_width, frac_bits))
        self.local_max   = Signal(reset=1)
        self.interpolate = Signal(reset=1)
        self.clear       = Signal()
        self.frame_error = Signal()
        self.count       = Signal(index_width + frac_bits)             # Records in the current CPI.
        self.last_count  = Signal(index_width + frac_bits)             # Records in the last CPI.
        self.cpi_count   = Signal(32)
        self.cpi_done    = Signal()

        # # #

        N, M, F = n_range_bins, n_doppler_bins, frac_bits
        adv  = Signal()
        busy = Signal()                                                 # A record is being formed.
        free = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            free.eq(adv & ~busy),
        ]

        # Beat sequencer: real cells (RUN) and the virtual column / row (FLUSH).
        # ----------------------------------------------------------------------
        col   = Signal(max=M + 1)                                       # Incoming column (M: virtual).
        row   = Signal(max=N + 1)                                       # Incoming row (N: virtual).
        beat  = Signal()
        real0 = Signal()
        xfer  = Signal()
        self.fsm = fsm = FSM(reset_state="RUN")
        fsm.act("RUN",
            self.sink.ready.eq(free),
            beat.eq(free & self.sink.valid),
            real0.eq(1),
            If(beat & (col == M - 1),
                NextState("FLUSH"),
            ),
        )
        fsm.act("FLUSH",
            beat.eq(free),
            If(beat & (col == M),
                If(row == N,
                    NextState("WAIT_LAST"),
                ).Elif(row == N - 1,
                    NextState("FLUSH"),                                 # The virtual row.
                ).Else(
                    NextState("RUN"),
                ),
            ),
        )
        v1 = Signal()
        fsm.act("WAIT_LAST",
            If(~v1 & ~busy & adv,
                NextState("TERM"),
            ),
        )
        term = Signal()
        fsm.act("TERM",
            term.eq(1),
            If(adv,
                NextState("RUN"),
            ),
        )
        self.comb += xfer.eq(self.sink.valid & self.sink.ready)
        self.sync += [
            If(beat,
                If(col == M,
                    col.eq(0),
                    If(row == N, row.eq(0)).Else(row.eq(row + 1)),
                ).Else(
                    col.eq(col + 1),
                ),
            ),
            If(self.clear,
                self.frame_error.eq(0),
            ).Elif(xfer & ((self.sink.first != (col == 0)) | (self.sink.last != (col == M - 1))),
                self.frame_error.eq(1),
            ),
        ]

        # Line buffers (rows r-1 and r-2 of the incoming row r), read at S0, written at S1.
        # ----------------------------------------------------------------------------------
        self.specials.buf1 = buf1 = Memory(data_width + 1, M)          # Previous row (value, detect).
        self.specials.buf0 = buf0 = Memory(data_width + 1, M)          # The row before.
        b1_rp, b1_wp = buf1.get_port(has_re=True), buf1.get_port(write_capable=True)
        b0_rp, b0_wp = buf0.get_port(has_re=True), buf0.get_port(write_capable=True)
        self.specials += b1_rp, b1_wp, b0_rp, b0_wp
        col_ok = Signal()
        self.comb += [
            col_ok.eq(col < M),
            b1_rp.adr.eq(col), b1_rp.re.eq(free),
            b0_rp.adr.eq(col), b0_rp.re.eq(free),
        ]

        # S1: the incoming cell with its column of the two stored rows; window shift on 'proc'.
        # -------------------------------------------------------------------------------------
        x1, d1 = Signal(data_width), Signal()
        col1   = Signal(max=M + 1)
        row1   = Signal(max=N + 1)
        proc   = Signal()
        self.sync += If(free,
            v1.eq(beat), col1.eq(col), row1.eq(row),
            x1.eq(Mux(real0 & self.sink.valid, self.sink.data, 0)),
            d1.eq(real0 & self.sink.valid & self.sink.detect),
        )
        self.comb += proc.eq(free & v1)
        colok1, top_ok, mid_ok, bot_ok = Signal(), Signal(), Signal(), Signal()
        cur_top, cur_mid, cur_bot = Signal(data_width), Signal(data_width), Signal()
        cur_mid_d = Signal()
        self.comb += [
            colok1.eq(col1 < M),
            top_ok.eq(colok1 & (row1 >= 2)),
            mid_ok.eq(colok1 & (row1 >= 1)),
            bot_ok.eq(colok1 & (row1 < N)),
            cur_top.eq(Mux(top_ok, b0_rp.dat_r[:data_width], 0)),
            cur_mid.eq(Mux(mid_ok, b1_rp.dat_r[:data_width], 0)),
            cur_mid_d.eq(mid_ok & b1_rp.dat_r[data_width]),
            # Row shift: the incoming cell into buf1, buf1's cell into buf0.
            b1_wp.adr.eq(col1), b1_wp.dat_w.eq(Cat(x1, d1)), b1_wp.we.eq(proc & colok1),
            b0_wp.adr.eq(col1), b0_wp.dat_w.eq(b1_rp.dat_r), b0_wp.we.eq(proc & colok1),
        ]
        cur_bot = Signal(data_width)
        self.comb += cur_bot.eq(Mux(bot_ok, x1, 0))
        # Window columns c-2 (index 0) and c-1 (index 1) of the three rows; the centre is
        # (row1 - 1, col1 - 1) = w_mid[1] with detect dc.
        w_top = [Signal(data_width, name=f"w_top{k}") for k in range(2)]
        w_mid = [Signal(data_width, name=f"w_mid{k}") for k in range(2)]
        w_bot = [Signal(data_width, name=f"w_bot{k}") for k in range(2)]
        dc    = Signal()
        self.sync += If(proc,
            w_top[1].eq(cur_top), w_mid[1].eq(cur_mid), w_bot[1].eq(cur_bot), dc.eq(cur_mid_d),
            If(col1 == 0,
                w_top[0].eq(0), w_mid[0].eq(0), w_bot[0].eq(0),
            ).Else(
                w_top[0].eq(w_top[1]), w_mid[0].eq(w_mid[1]), w_bot[0].eq(w_bot[1]),
            ),
        )
        y0 = w_mid[1]
        strict = Signal()
        loose  = Signal()
        centre_ok = Signal()
        peak = Signal()
        self.comb += [
            strict.eq((y0 > w_top[0]) & (y0 > w_top[1]) & (y0 > cur_top) & (y0 > w_mid[0])),
            loose.eq((y0 >= cur_mid) & (y0 >= w_bot[0]) & (y0 >= w_bot[1]) & (y0 >= cur_bot)),
            centre_ok.eq((col1 >= 1) & (row1 >= 1)),
            peak.eq(proc & centre_ok & dc & (~self.local_max | (strict & loose))),
        ]

        # Record formation: latch the cross, bit-serial parabolic interpolation per axis.
        # -------------------------------------------------------------------------------
        r0, c0 = Signal(max=N), Signal(max=M)
        yc     = Signal(data_width)
        num    = [Signal((data_width + 1, True), name=f"num{k}") for k in range(2)]   # (S - N), (E - W).
        den    = [Signal((data_width + 3, True), name=f"den{k}") for k in range(2)]   # 2 (2 y0 - yL - yR).
        rem    = [Signal(data_width + 3, name=f"rem{k}") for k in range(2)]
        q      = [Signal(F, name=f"q{k}") for k in range(2)]
        neg    = [Signal(name=f"neg{k}") for k in range(2)]
        clampd = [Signal(name=f"clamp{k}") for k in range(2)]
        step   = Signal(max=F + 1)
        # Signed copies (explicit widths: keep every shift/sum out of Verilog's self-determined
        # contexts).
        y0s, ns, ss, ws, es = [Signal((data_width + 1, True), name=n) for n in ("y0s", "ns", "ss", "ws", "es")]
        curv = [Signal((data_width + 2, True), name=f"curv{k}") for k in range(2)]
        self.comb += [
            y0s.eq(y0), ns.eq(w_top[1]), ss.eq(w_bot[1]), ws.eq(w_mid[0]), es.eq(cur_mid),
            curv[0].eq(y0s + y0s - ns - ss),
            curv[1].eq(y0s + y0s - ws - es),
        ]
        self.sync += If(peak,
            r0.eq(row1 - 1), c0.eq(col1 - 1), yc.eq(y0),
            num[0].eq(ss - ns),
            num[1].eq(es - ws),
            den[0].eq(curv[0] + curv[0]),
            den[1].eq(curv[1] + curv[1]),
        )
        self.div = div = FSM(reset_state="IDLE")
        div.act("IDLE",
            If(peak,
                NextValue(busy, 1),
                If(self.interpolate, NextState("SETUP")).Else(NextState("EMIT")),
            ),
        )
        div.act("SETUP",
            NextValue(step, 0),
            *[NextValue(neg[k], num[k] < 0) for k in range(2)],
            *[NextValue(rem[k], Mux(num[k] < 0, -num[k], num[k])) for k in range(2)],
            *[NextValue(q[k], 0) for k in range(2)],
            NextState("CHECK"),
        )
        rem2 = [Signal(data_width + 4, name=f"rem2_{k}") for k in range(2)]
        self.comb += [rem2[k].eq(rem[k] << 1) for k in range(2)]
        div.act("CHECK",
            # Not a maximum along this axis (or exactly half way): clamp to +/-0.5 bin or 0.
            *[NextValue(clampd[k], (den[k] <= 0) | (rem2[k] >= den[k])) for k in range(2)],
            NextState("DIVIDE"),
        )
        div.act("DIVIDE",
            *[If(rem2[k] >= den[k],
                NextValue(rem[k], rem2[k] - den[k]), NextValue(q[k], Cat(1, q[k][:-1])) if F > 1 else NextValue(q[k], 1),
            ).Else(
                NextValue(rem[k], rem2[k]), NextValue(q[k], Cat(0, q[k][:-1])) if F > 1 else NextValue(q[k], 0),
            ) for k in range(2)],
            NextValue(step, step + 1),
            If(step == F - 1, NextState("EMIT")),
        )
        # Sub-bin offsets: +/-q (Q.F, |q| < 2^(F-1) when not clamped), clamps at +/-2^(F-1) or 0.
        delta = [Signal((F + 2, True), name=f"delta{k}") for k in range(2)]
        for k in range(2):
            self.comb += delta[k].eq(Mux(self.interpolate, Mux(clampd[k],
                Mux(den[k] <= 0, 0, Mux(neg[k], -(1 << (F - 1)), 1 << (F - 1))),
                Mux(neg[k], -q[k], q[k])), 0))
        PW = index_width + F
        base = [Signal(PW, name=f"base{k}") for k in range(2)]
        pos  = [Signal((PW + 2, True), name=f"pos{k}") for k in range(2)]
        posc = [Signal(PW, name=f"posc{k}") for k in range(2)]
        self.comb += [
            base[0].eq(r0 << F), base[1].eq(c0 << F),
            pos[0].eq(base[0] + delta[0]), pos[1].eq(base[1] + delta[1]),
            *[posc[k].eq(Mux(pos[k] < 0, 0, pos[k][:PW])) for k in range(2)],
        ]
        emit = Signal()
        div.act("EMIT",
            emit.eq(1),
            If(adv,
                NextValue(busy, 0),
                NextState("IDLE"),
            ),
        )

        # Output register: records and the per-CPI terminator.
        # -----------------------------------------------------
        self.sync += [
            self.cpi_done.eq(0),
            If(adv,
                self.source.valid.eq(emit | term),
                self.source.hit.eq(emit),
                self.source.first.eq(self.count == 0),
                self.source.last.eq(term),
                If(emit,
                    self.source.range.eq(posc[0]),
                    self.source.doppler.eq(posc[1]),
                    self.source.data.eq(yc),
                    self.count.eq(self.count + 1),
                ),
                If(term,
                    self.source.range.eq(0),
                    self.source.doppler.eq(0),
                    self.source.data.eq(self.count),
                    self.count.eq(0),
                    self.last_count.eq(self.count),
                    self.cpi_count.eq(self.cpi_count + 1),
                    self.cpi_done.eq(1),
                ),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("local_max",   size=1, offset=0, reset=1, description="Only local maxima become records."),
            CSRField("interpolate", size=1, offset=1, reset=1, description="Parabolic sub-bin interpolation."),
            CSRField("clear",       size=1, offset=2, pulse=True, description="Clear the frame error."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_range_bins",   size=12, offset=0,  description="Rows per CPI."),
            CSRField("n_doppler_bins", size=12, offset=12, description="Cells per row."),
            CSRField("frac_bits",      size=4,  offset=24, description="Sub-bin fractional bits."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("frame_error", size=1, offset=0, description="Sticky: row framing did not match n_doppler_bins."),
        ])
        self._count     = CSRStatus(self.index_width + self.frac_bits, name="count", description="Records in the last CPI.")
        self._cpi_count = CSRStatus(32, name="cpi_count", description="CPIs processed since reset.")
        self.comb += [
            self.local_max.eq(self._control.fields.local_max),
            self.interpolate.eq(self._control.fields.interpolate),
            self.clear.eq(self._control.fields.clear),
            self._config.fields.n_range_bins.eq(self.n_range_bins),
            self._config.fields.n_doppler_bins.eq(self.n_doppler_bins),
            self._config.fields.frac_bits.eq(self.frac_bits),
            self._status.fields.frame_error.eq(self.frame_error),
            self._count.status.eq(self.last_count),
            self._cpi_count.status.eq(self.cpi_count),
        ]

    def add_irq(self):
        self.ev     = EventManager()
        self.ev.cpi = EventSourcePulse(description="A CPI's target burst has been closed.")
        self.ev.finalize()
        self.comb += self.ev.cpi.trigger.eq(self.cpi_done)
