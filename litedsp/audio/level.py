#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import (check, tdm_layout, tdm_channel, tdm_channel_bits, rounded, saturated,
    scaled, add_bypass, add_bypass_csr)

# Volume -------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPVolume(LiteXModule):
    """Per-channel volume with zipper-free gain ramping and mute on a TDM audio stream.

    Each channel has an unsigned Q5.``gain_frac`` gain (1.0 = ``2**gain_frac``, up to +30 dB)
    and a mute bit; the applied gain slews toward its target by ``delta >> ramp_shift`` per
    sample of that channel (at least one LSB, so it converges exactly): a step of ``D`` in
    the target is reached in ``~ramp_shift*ln(2)*log2(D)`` samples without zipper noise, a
    mute fades to exact zero. ``ramp_enable=0`` applies targets immediately. The product is
    rounded once and saturated (sticky ``sat``). ``n_channels=1`` is a mono block on
    ``real_layout``. Latency 2, one multiplier.

    Parameters
    ----------
    n_channels : int
        Channels in the TDM frame (1 = mono, real layout).
    gain_frac : int
        Fractional bits of the gains (default ``data_width - 5``).
    ramp_shift : int
        Ramp speed: the gain moves by (target - gain) >> ramp_shift per sample.
    """
    def __init__(self, data_width=24, n_channels=2, gain_frac=None, ramp_shift=8, with_csr=True):
        if gain_frac is None:
            gain_frac = data_width - 5
        check(data_width >= 8, "expected data_width >= 8")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(ramp_shift >= 1, "expected ramp_shift >= 1")
        check(1 <= gain_frac <= data_width - 2, "expected 1 <= gain_frac <= data_width - 2")
        self.data_width = data_width
        self.n_channels = n_channels
        self.gain_frac  = gain_frac
        self.gain_width = gain_frac + 5
        self.ramp_shift = ramp_shift
        self.latency    = 2
        GW = self.gain_width
        self.sink   = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.gains  = [Signal(GW, reset=1 << gain_frac, name=f"gain{c}") for c in range(n_channels)]
        self.mute        = Signal(n_channels)                          # Per-channel mute.
        self.ramp_enable = Signal(reset=1)
        self.clear_sat   = Signal()
        self.sat         = Signal()

        # # #

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]
        ch = tdm_channel(self.sink)

        # Gain ramp for the beat's channel.
        # ---------------------------------
        applied = [Signal(GW, reset=1 << gain_frac, name=f"applied{c}") for c in range(n_channels)]
        g_cur   = Signal(GW)
        target  = Signal(GW)
        delta   = Signal((GW + 1, True))
        step    = Signal((GW + 1, True))
        g_next  = Signal(GW)
        self.comb += [
            g_cur.eq(Array(applied)[ch]),
            target.eq(Mux(Array([self.mute[c] for c in range(n_channels)])[ch], 0,
                          Array(self.gains)[ch])),
            delta.eq(target - g_cur),
            step.eq(Mux(delta == 0, 0,
                    Mux((delta >> ramp_shift) != 0, delta >> ramp_shift, Mux(delta[-1], -1, 1)))),
            g_next.eq(Mux(self.ramp_enable, g_cur + step, target)),
        ]
        for c in range(n_channels):
            self.sync += If(xfer & (ch == c), applied[c].eq(g_next))

        # Stage 1: register sample + gain; stage 2: product, round + saturate.
        # ------------------------------------------------------------------
        x1, g1 = Signal((data_width, True)), Signal(GW)
        v1, f1, l1 = Signal(), Signal(), Signal()
        ch1  = Signal(tdm_channel_bits(n_channels))
        prod = Signal((data_width + GW + 1, True))
        self.sync += If(adv,
            x1.eq(self.sink.data), g1.eq(g_next), v1.eq(self.sink.valid),
            f1.eq(self.sink.first), l1.eq(self.sink.last), ch1.eq(ch),
        )
        self.comb += prod.eq(x1*g1)
        out, ovf = scaled(prod, gain_frac, data_width)
        self.sync += If(adv,
            self.source.data.eq(out),
            self.source.valid.eq(v1),
            self.source.first.eq(f1),
            self.source.last.eq(l1),
        )
        if n_channels > 1:
            self.sync += If(adv, self.source.channel.eq(ch1))
        self.sync += If(self.clear_sat, self.sat.eq(0)).Elif(adv & v1 & ovf, self.sat.eq(1))
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        for c, g in enumerate(self.gains):
            csr = CSRStorage(self.gain_width, reset=1 << self.gain_frac, name=f"gain{c}",
                description=f"Channel {c} gain (unsigned Q5.{self.gain_frac}, 1.0 = "
                            f"2**{self.gain_frac}).")
            setattr(self, f"_gain{c}", csr)
            self.comb += g.eq(csr.storage)
        self._control = CSRStorage(fields=[
            CSRField("mute",        size=self.n_channels, offset=0, description="Per-channel mute (faded)."),
            CSRField("ramp_enable", size=1, offset=8, reset=1, description="Ramp gain changes."),
            CSRField("clear_sat",   size=1, offset=9, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturation", size=1, description="Output saturated since the last clear."),
        ])
        self.comb += [
            self.mute.eq(self._control.fields.mute),
            self.ramp_enable.eq(self._control.fields.ramp_enable),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturation.eq(self.sat),
        ]
        add_bypass_csr(self)

# Stereo Matrix ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPStereoMatrix(LiteXModule):
    """2x2 matrix on a stereo TDM stream: ``L' = a*L + b*R``, ``R' = c*L + d*R``.

    Mid/side encode (``a = b = c = 0.5, d = -0.5``) and decode (``1, 1, 1, -1``),
    constant-power panning, width control, channel swap or mono fold-down are all coefficient
    presets (see ``StereoMatrixDriver``). Coefficients are signed Q3.``coeff_frac``; each output
    is rounded once and saturated (sticky ``sat``). A serial engine accepts the L beat (channel
    0) then the R beat, computes the four products on one multiplier and emits the two output
    beats; beats arriving out of order set the sticky ``sequence_error`` and are dropped.
    ``cycles_per_frame = 8``; ``bypass`` passes beats through (latency 1).

    Parameters
    ----------
    coeff_width : int
        Width of the signed coefficients.
    coeff_frac : int
        Fractional bits of the coefficients (1.0 = 2**coeff_frac, must be < coeff_width - 1).
    """
    def __init__(self, data_width=24, coeff_width=18, coeff_frac=15, with_csr=True):
        check(data_width >= 8, "expected data_width >= 8")
        check(0 < coeff_frac < coeff_width - 1, "expected 0 < coeff_frac < coeff_width - 1")
        self.data_width  = data_width
        self.coeff_width = coeff_width
        self.coeff_frac  = coeff_frac
        self.cycles_per_frame = 8
        self.latency     = 4                                           # From the R beat to L'.
        self.sink   = stream.Endpoint(tdm_layout(data_width, 2))
        self.source = stream.Endpoint(tdm_layout(data_width, 2))
        one = 1 << coeff_frac
        self.a = Signal((coeff_width, True), reset=one)
        self.b = Signal((coeff_width, True))
        self.c = Signal((coeff_width, True))
        self.d = Signal((coeff_width, True), reset=one)
        self.bypass         = Signal()
        self.clear_sat      = Signal()
        self.sat            = Signal()
        self.sequence_error = Signal()

        # # #

        AW  = data_width + coeff_width + 2
        l_in, r_in = Signal((data_width, True)), Signal((data_width, True))
        first_l, last_r = Signal(), Signal()
        acc_l, acc_r = Signal((AW, True)), Signal((AW, True))
        op_x  = Signal((data_width, True))
        op_k  = Signal((coeff_width, True))
        prod  = Signal((data_width + coeff_width, True))
        self.comb += prod.eq(op_x*op_k)
        out_l, ovf_l = scaled(acc_l, coeff_frac, data_width)
        out_r, ovf_r = scaled(acc_r, coeff_frac, data_width)

        # Bypass path (beat-by-beat register).
        # ------------------------------------
        byp_valid = Signal()
        byp_data  = Signal((data_width, True))
        byp_ch    = Signal()
        byp_first, byp_last = Signal(), Signal()
        byp_adv   = Signal()
        self.comb += byp_adv.eq(self.source.ready | ~byp_valid)
        self.sync += If(byp_adv,
            byp_valid.eq(self.sink.valid & self.bypass),
            byp_data.eq(self.sink.data), byp_ch.eq(self.sink.channel),
            byp_first.eq(self.sink.first), byp_last.eq(self.sink.last),
        )

        # Engine.
        # -------
        self.fsm = fsm = FSM(reset_state="IDLE")
        eng_ready = Signal()
        eng_valid = Signal()
        eng_data  = Signal((data_width, True))
        eng_ch    = Signal()
        eng_first, eng_last = Signal(), Signal()
        seq_err   = Signal()
        fsm.act("IDLE",
            eng_ready.eq(1),
            If(self.sink.valid & ~self.bypass,
                If(self.sink.channel == 0,
                    NextValue(l_in, self.sink.data),
                    NextValue(first_l, self.sink.first),
                    NextState("WAIT_R"),
                ).Else(
                    seq_err.eq(1),
                ),
            ),
        )
        fsm.act("WAIT_R",
            eng_ready.eq(1),
            If(self.sink.valid,
                If(self.sink.channel == 1,
                    NextValue(r_in, self.sink.data),
                    NextValue(last_r, self.sink.last),
                    NextState("MAC0"),
                ).Else(
                    seq_err.eq(1),
                    NextValue(l_in, self.sink.data),             # Restart with this L.
                    NextValue(first_l, self.sink.first),
                ),
            ),
        )
        fsm.act("MAC0", op_x.eq(l_in), op_k.eq(self.a), NextValue(acc_l, prod), NextState("MAC1"))
        fsm.act("MAC1", op_x.eq(r_in), op_k.eq(self.b), NextValue(acc_l, acc_l + prod),
                NextState("MAC2"))
        fsm.act("MAC2", op_x.eq(l_in), op_k.eq(self.c), NextValue(acc_r, prod), NextState("MAC3"))
        fsm.act("MAC3", op_x.eq(r_in), op_k.eq(self.d), NextValue(acc_r, acc_r + prod),
                NextState("OUT_L"))
        fsm.act("OUT_L",
            eng_valid.eq(1), eng_data.eq(out_l), eng_ch.eq(0), eng_first.eq(first_l),
            If(self.source.ready,
                NextValue(self.sat, self.sat | ovf_l),
                NextState("OUT_R"),
            ),
        )
        fsm.act("OUT_R",
            eng_valid.eq(1), eng_data.eq(out_r), eng_ch.eq(1), eng_last.eq(last_r),
            If(self.source.ready,
                NextValue(self.sat, self.sat | ovf_r),
                NextState("IDLE"),
            ),
        )
        self.sync += [
            If(self.clear_sat, self.sat.eq(0), self.sequence_error.eq(0)),
            If(seq_err, self.sequence_error.eq(1)),
        ]

        # Output mux.
        # -----------
        self.comb += If(self.bypass,
            self.sink.ready.eq(byp_adv),
            self.source.valid.eq(byp_valid),
            self.source.data.eq(byp_data), self.source.channel.eq(byp_ch),
            self.source.first.eq(byp_first), self.source.last.eq(byp_last),
        ).Else(
            self.sink.ready.eq(eng_ready),
            self.source.valid.eq(eng_valid),
            self.source.data.eq(eng_data), self.source.channel.eq(eng_ch),
            self.source.first.eq(eng_first), self.source.last.eq(eng_last),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        cw, cf = self.coeff_width, self.coeff_frac
        for name, sig in (("a", self.a), ("b", self.b), ("c", self.c), ("d", self.d)):
            csr = CSRStorage(cw, reset=sig.reset.value, name=name,
                description=f"Matrix coefficient {name} (signed Q{cw - cf}.{cf}).")
            setattr(self, f"_{name}", csr)
            self.comb += sig.eq(csr.storage)
        self._control = CSRStorage(fields=[
            CSRField("bypass",    size=1, offset=0, description="Pass beats through unchanged."),
            CSRField("clear_sat", size=1, offset=1, pulse=True, description="Clear saturation / sequence flags."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturation",     size=1, offset=0, description="An output saturated since the last clear."),
            CSRField("sequence_error", size=1, offset=1, description="A beat arrived out of L/R order."),
        ])
        self.comb += [
            self.bypass.eq(self._control.fields.bypass),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturation.eq(self.sat),
            self._status.fields.sequence_error.eq(self.sequence_error),
        ]
