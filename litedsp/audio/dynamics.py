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

from litedsp.common       import check, tdm_layout, tdm_channel, tdm_channel_bits, scaled
from litedsp.level.logdb  import LiteDSPLog2, LiteDSPExp2

# Presets ------------------------------------------------------------------------------------------

PRESETS = ("compressor", "limiter", "gate")

def _log2_q8(db):
    return int(round(db/(20*math.log10(2))*256))

def _alpha(ms, fs=48000):
    return 65535 if ms <= 0 else int(round((1 - math.exp(-1/(ms*1e-3*fs)))*65536))

# (threshold Q.8, slope_above Q4.16, slope_below Q4.16, attack alpha, release alpha, gr_max Q7.8)
PRESET_VALUES = {
    "compressor": (_log2_q8(-20), int(0.75*65536), 0,               _alpha(10), _alpha(100), _log2_q8(60)),
    "limiter":    (_log2_q8(-1),  65536,           0,               _alpha(0),  _alpha(50),  _log2_q8(60)),
    "gate":       (_log2_q8(-50), 0,               int(7.0*65536),  _alpha(1),  _alpha(100), _log2_q8(60)),
}

# Compressor / Limiter / Gate ----------------------------------------------------------------------

@ResetInserter()
class LiteDSPCompressor(LiteXModule):
    """Dynamics processor (compressor, limiter, expander/gate) with a log-domain gain computer.

    Per beat of the TDM stream the sidechain measures the level ``L`` of the channel in the
    log2 domain (Q.8: ``L = log2(|x| / FS)``, peak, or half the log of a per-channel
    one-pole mean square, ``detector = 1``, through :class:`~litedsp.level.logdb.LiteDSPLog2`
    with its LUT mantissa), computes the gain reduction ``gr = slope_above*max(L - threshold,
    0) + slope_below*max(threshold - L, 0)`` (hard knee; ``slope_above = 1 - 1/ratio`` for a
    compressor, 1.0 for a limiter; ``slope_below = ratio - 1`` for an expander/gate), clamped
    to ``gr_max``, smooths it with attack/release one-pole coefficients (Q0.16, state in
    Q7.24 so slow releases have no dead band), applies ``makeup`` and converts the log gain
    back through :class:`~litedsp.level.logdb.LiteDSPExp2` (Q5.19, up to +24 dB); the gain
    multiplies the sample delayed by ``lookahead`` frames (the sidechain sees the undelayed
    sample, so a limiter can act before the peak). ``stereo_link`` drives all channels from
    the loudest channel of the previous frame with one shared smoother. ``preset`` only sets
    the control reset values; every parameter is a runtime control. One shared multiplier;
    ``cycles_per_sample`` is documented by the ``cycles_per_sample`` attribute (about 16).

    Parameters
    ----------
    n_channels : int
        Channels in the TDM frame (1 = mono, real layout).
    lookahead : int
        Delay of the gain-applied signal in frames (0 = none).
    preset : str
        ``"compressor"`` (-20 dB, 4:1, 10/100 ms), ``"limiter"`` (-1 dBFS, instant attack,
        50 ms release) or ``"gate"`` (-50 dB, 1:8, 1/100 ms): reset values of the controls.
    """
    def __init__(self, data_width=24, n_channels=2, lookahead=0, preset="compressor",
        with_csr=True):
        check(data_width >= 8, "expected data_width >= 8")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(lookahead >= 0, "expected lookahead >= 0")
        check(preset in PRESETS, f"expected preset in {PRESETS}")
        self.data_width = data_width
        self.n_channels = n_channels
        self.lookahead  = lookahead
        self.preset     = preset
        DW = data_width
        thr, s_above, s_below, att, rel, gr_max = PRESET_VALUES[preset]
        self.sink   = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.threshold   = Signal((16, True), reset=thr)                 # Q.8 log2 re FS.
        self.slope_above = Signal(20, reset=s_above)                     # Q4.16.
        self.slope_below = Signal(20, reset=s_below)                     # Q4.16.
        self.attack      = Signal(17, reset=att)                         # Q0.16 (65536 = 1.0).
        self.release     = Signal(17, reset=rel)
        self.gr_max      = Signal(15, reset=gr_max)                      # Q7.8.
        self.makeup      = Signal((16, True))                            # Q.8 log2 gain.
        self.detector    = Signal()                                      # 0 peak, 1 rms.
        self.rms_shift   = Signal(4, reset=6)
        self.stereo_link = Signal()
        self.bypass      = Signal()
        self.clear_sat   = Signal()
        self.sat         = Signal()
        self.gain_reduction = Signal(15)                                 # Last gr (Q7.8).

        # # #

        n_ch_bits = tdm_channel_bits(n_channels)
        L_OFF_PK  = (2*DW - 1)*256
        L_OFF_RMS = (DW - 1)*256

        # Sub-blocks: log2 (LUT mantissa) on a 2*DW-bit magnitude, exp2 to a Q5.19 gain.
        # ---------------------------------------------------------------------------
        self.log2 = log2 = LiteDSPLog2(in_width=2*DW, frac_bits=8, lut=True, with_csr=False)
        self.exp2 = exp2 = LiteDSPExp2(in_width=16, frac_bits=8, out_frac=19, out_width=24, with_csr=False)
        self.comb += [log2.source.ready.eq(1), exp2.source.ready.eq(1)]

        # Beat registers, per-channel state (mean square, smoothed gain reduction).
        # -----------------------------------------------------------------------
        x     = Signal((DW, True))
        x_del = Signal((DW, True))
        ch    = Signal(n_ch_bits)
        first, last = Signal(), Signal()
        mag   = Signal(DW)
        sq    = [Signal(2*DW, name=f"sq{c}") for c in range(n_channels)]
        gr_s  = [Signal(31, name=f"gr_s{c}") for c in range(n_channels)]
        sidx  = Signal(n_ch_bits)
        self.comb += [
            mag.eq(Mux(x[-1], -x, x)),
            sidx.eq(Mux(self.stereo_link, 0, ch)),
        ]
        sq_cur   = Signal(2*DW)
        gr_s_cur = Signal(31)
        self.comb += [sq_cur.eq(Array(sq)[ch]), gr_s_cur.eq(Array(gr_s)[sidx])]

        # Lookahead RAM (x delayed by `lookahead` frames of the same channel).
        # ------------------------------------------------------------------
        if lookahead > 0:
            depth = 1
            while depth < lookahead*n_channels + 1:
                depth *= 2
            la     = Memory(DW, depth)
            la_wr  = la.get_port(write_capable=True)
            la_rd  = la.get_port(async_read=True)
            self.specials += la, la_wr, la_rd
            wptr = Signal(max=depth)
            self.comb += [
                la_wr.adr.eq(wptr), la_wr.dat_w.eq(self.sink.data),
                la_rd.adr.eq(wptr - lookahead*n_channels),
            ]
            self.sync += If(la_wr.we, wptr.eq(wptr + 1))
            x_delayed_in = la_rd.dat_r
        else:
            x_delayed_in = self.sink.data

        # Shared multiplier.
        # ------------------
        op_a  = Signal((50, True))
        op_b  = Signal((25, True))
        prod  = Signal((75, True))
        self.sync += prod.eq(op_a*op_b)

        # Level, gain computer, smoother, gain.
        # ------------------------------------
        L      = Signal((16, True))                                       # Q.8 log2 re FS.
        L_max  = Signal((16, True), reset=-(1 << 15))
        L_link = Signal((16, True), reset=-(1 << 15))
        L_use  = Signal((16, True))
        over   = Signal((17, True))
        gr_raw = Signal(21)
        gr     = Signal(15)
        err    = Signal((32, True))
        alpha  = Signal(17)
        gr_s_n = Signal((33, True))
        gr_s_c = Signal(31)
        g_log  = Signal((17, True))
        g_clip = Signal((16, True))
        gain   = Signal(24)
        x2     = Signal(2*DW)
        sq_dif = Signal((2*DW + 2, True))
        sq_new = Signal((2*DW + 2, True))
        sq_upd = Signal(2*DW)
        gr_tgt = Signal(31)
        y      = Signal((DW, True))
        ovf    = Signal()
        self.comb += [
            L_use.eq(Mux(self.stereo_link, L_link, L)),
            over.eq(L_use - self.threshold),
            gr_raw.eq(prod[16:37]),
            gr.eq(Mux(gr_raw > self.gr_max, self.gr_max, gr_raw)),
            gr_tgt.eq(gr << 16),
            err.eq(gr_tgt - gr_s_cur),
            alpha.eq(Mux(gr_tgt > gr_s_cur, self.attack, self.release)),
            gr_s_n.eq(gr_s_cur + (prod >> 16)),
            gr_s_c.eq(Mux(gr_s_n < 0, 0, Mux(gr_s_n > (1 << 31) - 1, (1 << 31) - 1, gr_s_n))),
            g_log.eq(self.makeup - (gr_s_c >> 16)),
            g_clip.eq(Mux(g_log > 4*256, 4*256, Mux(g_log < -47*256, -47*256, g_log))),
            x2.eq(prod[0:2*DW]),
            sq_dif.eq(x2 - sq_cur),
            sq_new.eq(sq_cur + (sq_dif >> self.rms_shift)),
            sq_upd.eq(Mux(sq_new < 0, 0, sq_new)),
        ]
        prod_y = Signal((DW + 24 + 1, True))                             # Signed view (a slice is unsigned).
        self.comb += prod_y.eq(prod[0:DW + 24 + 1])
        y_s, ovf_s = scaled(prod_y, 19, DW)
        self.comb += [y.eq(y_s), ovf.eq(ovf_s)]

        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(~self.bypass,
                self.sink.ready.eq(1),
                If(self.sink.valid,
                    NextValue(x, self.sink.data),
                    NextValue(x_del, x_delayed_in),
                    NextValue(ch, tdm_channel(self.sink)),
                    NextValue(first, self.sink.first),
                    NextValue(last, self.sink.last),
                    NextState("SQUARE"),
                ),
            ),
        )
        if lookahead > 0:
            self.comb += la_wr.we.eq(fsm.ongoing("IDLE") & ~self.bypass & self.sink.valid)
        fsm.act("SQUARE",
            op_a.eq(x), op_b.eq(x),                                       # prod = x*x next cycle.
            NextState("LEVEL"),
        )
        fsm.act("LEVEL",
            *[If(ch == c, NextValue(sq[c], sq_upd)) for c in range(n_channels)],
            log2.sink.valid.eq(1),
            log2.sink.data.eq(Mux(self.detector, sq_upd, mag << DW)),
            NextState("WAIT_LOG"),
        )
        fsm.act("WAIT_LOG",
            If(log2.source.valid,
                NextValue(L, Mux(self.detector,
                    (log2.source.data >> 1) - L_OFF_RMS, log2.source.data - L_OFF_PK)),
                NextState("OVER"),
            ),
        )
        fsm.act("OVER",
            # Frame maximum for the stereo link (latched at the last channel of the frame).
            If(L > L_max, NextValue(L_max, L)),
            If(ch == n_channels - 1,
                NextValue(L_link, Mux(L > L_max, L, L_max)),
                NextValue(L_max, -(1 << 15)),
            ),
            op_a.eq(Mux(over[-1], self.slope_below, self.slope_above)),
            op_b.eq(Mux(over[-1], -over, over)),                          # slope * |over|.
            NextState("GR"),
        )
        fsm.act("GR",
            NextValue(self.gain_reduction, gr),
            op_a.eq(err), op_b.eq(alpha),                                 # err * alpha.
            NextState("SMOOTH"),
        )
        fsm.act("SMOOTH",
            *[If(sidx == c, NextValue(gr_s[c], gr_s_c)) for c in range(n_channels)],
            exp2.sink.valid.eq(1),
            exp2.sink.data.eq(g_clip),
            NextState("WAIT_EXP"),
        )
        fsm.act("WAIT_EXP",
            If(exp2.source.valid,
                NextValue(gain, exp2.source.data),
                NextState("MUL"),
            ),
        )
        fsm.act("MUL",
            op_a.eq(x_del), op_b.eq(gain),                                # x_delayed * gain.
            NextState("OUT"),
        )
        fsm.act("OUT",
            op_a.eq(x_del), op_b.eq(gain),                                # Hold the product.
            self.source.valid.eq(1),
            If(self.source.ready,
                If(ovf, NextValue(self.sat, 1)),
                NextState("IDLE"),
            ),
        )
        self.cycles_per_sample = 16
        self.latency           = 15

        # Output / bypass.
        # ----------------
        self.comb += If(self.bypass,
            self.sink.connect(self.source),
        ).Else(
            self.source.data.eq(y),
            self.source.first.eq(first),
            self.source.last.eq(last),
        )
        if n_channels > 1:
            self.comb += If(~self.bypass, self.source.channel.eq(ch))
        self.sync += If(self.clear_sat, self.sat.eq(0))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._threshold   = CSRStorage(16, reset=self.threshold.reset.value & 0xFFFF, name="threshold",
            description="Threshold in log2 units re full scale (signed Q.8: 256 = 6.02 dB).")
        self._slope_above = CSRStorage(20, reset=self.slope_above.reset.value, name="slope_above",
            description="Gain-reduction slope above the threshold (Q4.16; 1 - 1/ratio, 1.0 = limiter).")
        self._slope_below = CSRStorage(20, reset=self.slope_below.reset.value, name="slope_below",
            description="Gain-reduction slope below the threshold (Q4.16; ratio - 1 for an expander/gate).")
        self._attack      = CSRStorage(17, reset=self.attack.reset.value, name="attack",
            description="Attack smoothing coefficient (Q0.16; 65535 = instantaneous).")
        self._release     = CSRStorage(17, reset=self.release.reset.value, name="release",
            description="Release smoothing coefficient (Q0.16).")
        self._gr_max      = CSRStorage(15, reset=self.gr_max.reset.value, name="gr_max",
            description="Maximum gain reduction (Q7.8 log2 units).")
        self._makeup      = CSRStorage(16, name="makeup", description="Make-up gain (signed Q.8 log2 units).")
        self._control = CSRStorage(fields=[
            CSRField("detector",    size=1, offset=0, description="0: peak, 1: RMS (one-pole mean square)."),
            CSRField("rms_shift",   size=4, offset=4, reset=6, description="RMS averaging shift."),
            CSRField("stereo_link", size=1, offset=8, description="Drive all channels from the loudest one."),
            CSRField("bypass",      size=1, offset=9, description="Pass beats through unchanged."),
            CSRField("clear_sat",   size=1, offset=10, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("gain_reduction", size=15, offset=0, description="Last gain reduction (Q7.8)."),
            CSRField("saturation",     size=1,  offset=16, description="Output saturated since the last clear."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_channels", size=8,  offset=0,  description="Channels in the TDM frame."),
            CSRField("lookahead",  size=16, offset=8,  description="Lookahead in frames."),
            CSRField("preset",     size=2,  offset=24, description="Detector / gain-computer preset.", values=[
                ("``0b00``", "compressor"), ("``0b01``", "limiter"), ("``0b10``", "gate")]),
        ])
        self.comb += [
            self.threshold.eq(self._threshold.storage),
            self.slope_above.eq(self._slope_above.storage),
            self.slope_below.eq(self._slope_below.storage),
            self.attack.eq(self._attack.storage),
            self.release.eq(self._release.storage),
            self.gr_max.eq(self._gr_max.storage),
            self.makeup.eq(self._makeup.storage),
            self.detector.eq(self._control.fields.detector),
            self.rms_shift.eq(self._control.fields.rms_shift),
            self.stereo_link.eq(self._control.fields.stereo_link),
            self.bypass.eq(self._control.fields.bypass),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.gain_reduction.eq(self.gain_reduction),
            self._status.fields.saturation.eq(self.sat),
            self._config.fields.n_channels.eq(self.n_channels),
            self._config.fields.lookahead.eq(self.lookahead),
            self._config.fields.preset.eq(PRESETS.index(self.preset)),
        ]
