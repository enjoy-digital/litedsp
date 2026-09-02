#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Time-domain audio effects: LFO, modulated delay line (echo / chorus / flanger, and the
feedback-comb and allpass primitive of the reverb), wet/dry mix and the Freeverb-style reverb."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common          import (check, real_layout, tdm_layout, tdm_channel, tdm_channel_bits,
    rounded, saturated, scaled)
from litedsp.generation.nco  import sincos_rom

# LFO ----------------------------------------------------------------------------------------------

LFO_SHAPES = ("sine", "triangle", "saw", "square")

@ResetInserter()
class LiteDSPLFO(LiteXModule):
    """Low-frequency oscillator: sine (quarter-wave ROM), triangle, saw or square, with amplitude.

    A ``phase_bits`` accumulator advances by ``phase_inc`` per accepted sample (the NCO's
    handshake: backpressure never skips or repeats a sample); the top phase bits select the
    shape sample, scaled by the Q1.15 ``amplitude``. Feeds the modulation input of
    :class:`LiteDSPDelayLine` (chorus / flanger / vibrato) or any control port. Latency 1.

    Parameters
    ----------
    phase_bits : int
        Accumulator width (frequency resolution ``f_s / 2**phase_bits``).
    lut_depth : int
        Sine ROM entries per period (power of two >= 8).
    """
    def __init__(self, phase_bits=32, data_width=16, lut_depth=256, with_csr=True):
        addr_bits = lut_depth.bit_length() - 1
        check(lut_depth >= 8 and (1 << addr_bits) == lut_depth, "lut_depth must be a power of two >= 8")
        check(phase_bits >= data_width + 2, "expected phase_bits >= data_width + 2")
        self.phase_bits = phase_bits
        self.data_width = data_width
        self.lut_depth  = lut_depth
        self.latency    = 1
        self.phase_inc  = Signal(phase_bits)
        self.shape      = Signal(2)
        self.amplitude  = Signal((data_width, True), reset=(1 << (data_width - 1)) - 1)
        self.source     = stream.Endpoint(real_layout(data_width))

        # # #

        DW = data_width
        FS = (1 << (DW - 1)) - 1
        phase      = Signal(phase_bits)
        phase_next = Signal(phase_bits)
        ce         = Signal()
        self.comb += [
            ce.eq(self.source.ready | ~self.source.valid),
            phase_next.eq(phase + self.phase_inc),
        ]
        self.sync += If(ce, phase.eq(phase_next), self.source.valid.eq(1))

        # Shapes from the next phase (sine: ROM registered read; others registered here).
        # ------------------------------------------------------------------------------
        _, sine = sincos_rom(self, phase_next[phase_bits - addr_bits:], ce, DW, lut_depth, quarter_wave=True)
        saw    = Signal((DW, True))
        tri    = Signal((DW + 1, True))
        square = Signal((DW, True))
        self.comb += [
            saw.eq(phase_next[phase_bits - DW:]),
            tri.eq(2*Mux(saw[-1], -saw, saw) - (1 << (DW - 1))),
            square.eq(Mux(saw[-1], -FS, FS)),
        ]
        shape_r = Signal((DW, True))
        shape_d = Signal(2)
        self.sync += If(ce,
            shape_r.eq(Mux(self.shape == 1, saturated(tri, DW), Mux(self.shape == 2, saw, square))),
            shape_d.eq(self.shape),
        )
        value = Signal((DW, True))
        prod  = Signal((2*DW, True))
        self.comb += [
            value.eq(Mux(shape_d == 0, sine, shape_r)),
            prod.eq(value*self.amplitude),
            self.source.data.eq(scaled(prod, DW - 1, DW)[0]),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._phase_inc = CSRStorage(self.phase_bits, name="phase_inc",
            description="Phase increment per sample (frequency = phase_inc * f_s / 2**phase_bits).")
        self._control = CSRStorage(fields=[
            CSRField("shape", size=2, offset=0, values=[
                ("``0b00``", "Sine."), ("``0b01``", "Triangle."), ("``0b10``", "Saw."), ("``0b11``", "Square.")]),
        ])
        self._amplitude = CSRStorage(self.data_width, reset=self.amplitude.reset.value, name="amplitude",
            description="Output amplitude (signed Q1.15, 1.0 = full scale).")
        self.comb += [
            self.phase_inc.eq(self._phase_inc.storage),
            self.shape.eq(self._control.fields.shape),
            self.amplitude.eq(self._amplitude.storage),
        ]

# Delay Line ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDelayLine(LiteXModule):
    """Feedback delay line with damping, wet/dry mix and optional modulated fractional delay.

    Per beat of the TDM stream (per-channel buffer and state): the delayed sample ``d`` is read
    ``delay`` frames back (with ``modulation=True``: ``delay + mod*mod_depth`` frames, ``mod``
    a Q1.15 sample from ``sink_mod`` consumed once per frame, with linear interpolation of the
    fractional part -- chorus / flanger / vibrato), low-pass filtered in the feedback path
    (``filt += (d - filt)*(1 - damping)``), written back as ``x + feedback*filt`` and mixed:
    ``y = dry*x + wet*d``. Coefficients are signed Q1.15 (``damping`` Q0.15). The same block
    is the reverb's feedback comb (``wet = 1, dry = 0``) and Schroeder allpass (``feedback =
    g, wet = 1, dry = -g, damping = 0``). One multiplier, ``cycles_per_sample`` 8 (10 with
    modulation), sticky saturation, bypass.

    Parameters
    ----------
    n_channels : int
        Channels in the TDM frame (1 = mono, real layout).
    max_delay : int
        Buffer length per channel in frames (power of two allocated).
    coeff_frac : int
        Fractional bits of the coefficients (15: Q1.15).
    modulation : bool
        Add the ``sink_mod`` modulation input and fractional interpolation.
    mod_frac : int
        Fractional delay bits used by the interpolation.
    """
    def __init__(self, data_width=24, n_channels=2, max_delay=4096, coeff_frac=15, modulation=False,
        mod_frac=8, with_csr=True):
        check(data_width >= 8, "expected data_width >= 8")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(max_delay >= 4, "expected max_delay >= 4")
        check(0 < coeff_frac <= 15, "expected 0 < coeff_frac <= 15")
        check(1 <= mod_frac <= 15, "expected 1 <= mod_frac <= 15")
        check(isinstance(modulation, bool), "expected modulation to be a bool")
        self.data_width = data_width
        self.n_channels = n_channels
        self.max_delay  = max_delay
        self.coeff_frac = coeff_frac
        self.modulation = modulation
        self.mod_frac   = mod_frac
        self.cycles_per_sample = 10 if modulation else 8
        self.latency    = self.cycles_per_sample - 1
        DW, CF, MF = data_width, coeff_frac, mod_frac
        depth = 1
        while depth < max_delay:
            depth *= 2
        self.depth = depth
        dbits = depth.bit_length() - 1
        cbits = tdm_channel_bits(n_channels)
        self.sink   = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))
        if modulation:
            self.sink_mod = stream.Endpoint(real_layout(16))
        self.delay     = Signal(dbits, reset=min(max_delay - 2, depth//2))
        self.feedback  = Signal((16, True))
        self.damping   = Signal(15)
        self.wet       = Signal((16, True), reset=1 << (CF - 1))
        self.dry       = Signal((16, True), reset=1 << (CF - 1))
        self.mod_depth = Signal(dbits)
        self.bypass    = Signal()
        self.clear_sat = Signal()
        self.sat       = Signal()

        # # #

        # Buffer (per channel: address = {ptr, ch}), per-channel damping state, frame pointer.
        # ------------------------------------------------------------------------------------
        buf   = Memory(DW, depth << cbits)
        buf_r = buf.get_port(async_read=True)
        buf_w = buf.get_port(write_capable=True)
        self.specials += buf, buf_r, buf_w
        ptr   = Signal(dbits)
        filt  = [Signal((DW, True), name=f"filt{c}") for c in range(n_channels)]
        x, ch = Signal((DW, True)), Signal(cbits)
        first, last = Signal(), Signal()
        mod   = Signal((16, True))
        f_cur = Signal((DW, True))
        self.comb += f_cur.eq(Array(filt)[ch])

        # Delay computation (integer + fraction), reads, arithmetic on one multiplier.
        # ----------------------------------------------------------------------------
        d_int  = Signal(dbits)                                             # Combinational delay.
        frac   = Signal(MF)
        d_int_r = Signal(dbits)                                            # Latched for the beat.
        frac_r  = Signal(MF)
        rd_adr = Signal(dbits)
        d0, d1 = Signal((DW, True)), Signal((DW, True))
        rd_val = Signal((DW, True))                                        # Signed buffer read.
        d      = Signal((DW, True))
        op_a   = Signal((DW + 1, True))
        op_b   = Signal((17, True))
        prod   = Signal((DW + 18, True))
        acc    = Signal((DW + 18, True))
        self.sync += prod.eq(op_a*op_b)
        self.comb += [buf_r.adr.eq(Cat(ch, rd_adr)), rd_val.eq(buf_r.dat_r)]
        if modulation:
            # delay + mod*mod_depth in Q.MF frames (the Q.15 product is rescaled), clamped to
            # [1, max_delay - 2] frames.
            d_full = Signal((dbits + MF + 2, True))
            d_clip = Signal((dbits + MF + 2, True))
            self.comb += [
                d_full.eq((self.delay << MF) + (prod >> (15 - MF))),
                d_clip.eq(Mux(d_full < (1 << MF), 1 << MF,
                          Mux(d_full > ((max_delay - 2) << MF), (max_delay - 2) << MF, d_full))),
                d_int.eq(d_clip[MF:MF + dbits]),
                frac.eq(d_clip[0:MF]),
            ]
        else:
            self.comb += [
                d_int.eq(Mux(self.delay < 1, 1, Mux(self.delay > max_delay - 2, max_delay - 2, self.delay))),
                frac.eq(0),
            ]
        one_minus_damp = Signal(16)
        self.comb += one_minus_damp.eq((1 << 15) - self.damping)
        interp = Signal((DW + 1, True))
        self.comb += interp.eq(d0 + (prod >> MF))                          # d0 + (d1 - d0)*frac.
        filt_n = Signal((DW + 1, True))
        self.comb += filt_n.eq(f_cur + (prod >> 15))                       # filt + (d - filt)*(1 - damp).
        wr_val = Signal((DW + 1, True))
        self.comb += wr_val.eq(x + (prod >> CF))                           # x + feedback*filt.
        y, ovf = scaled(acc, CF, DW)

        self.fsm = fsm = FSM(reset_state="IDLE")
        mod_needed = Signal()                                              # Channel-0 beat: join mod.
        accept     = Signal()
        if modulation:
            self.comb += [
                mod_needed.eq(tdm_channel(self.sink) == 0),
                accept.eq(self.sink.valid & (~mod_needed | self.sink_mod.valid)),
                self.sink_mod.ready.eq(fsm.ongoing("IDLE") & ~self.bypass & self.sink.valid & mod_needed),
            ]
        else:
            self.comb += accept.eq(self.sink.valid)
        fsm.act("IDLE",
            If(~self.bypass,
                self.sink.ready.eq(accept),
                If(accept,
                    NextValue(x, self.sink.data),
                    NextValue(ch, tdm_channel(self.sink)),
                    NextValue(first, self.sink.first),
                    NextValue(last, self.sink.last),
                    *([If(mod_needed, NextValue(mod, self.sink_mod.data))] if modulation else
                      [NextValue(d_int_r, d_int), NextValue(frac_r, 0)]),
                    NextState("MODDEPTH" if modulation else "READ0"),
                ),
            ),
        )
        if modulation:
            fsm.act("MODDEPTH",
                op_a.eq(self.mod_depth), op_b.eq(mod),                    # mod*mod_depth (Q.15 -> frac).
                NextState("MODSHIFT"),
            )
            fsm.act("MODSHIFT",
                NextValue(d_int_r, d_int),                                # From prod = mod*mod_depth.
                NextValue(frac_r, frac),
                NextState("READ0"),
            )
        fsm.act("READ0",
            rd_adr.eq(ptr - d_int_r),
            NextValue(d0, rd_val),
            NextState("READ1"),
        )
        fsm.act("READ1",
            rd_adr.eq(ptr - d_int_r - 1),
            NextValue(d1, rd_val),
            op_a.eq(rd_val - d0), op_b.eq(frac_r),                        # (d1 - d0)*frac.
            NextState("INTERP"),
        )
        fsm.act("INTERP",
            NextValue(d, saturated(interp, DW) if modulation else d0),
            NextState("DAMP0"),
        )
        fsm.act("DAMP0",
            op_a.eq(d - f_cur), op_b.eq(one_minus_damp),                  # (d - filt)*(1 - damp).
            NextState("DAMP1"),
        )
        fsm.act("DAMP1",
            *[If(ch == c, NextValue(filt[c], saturated(filt_n, DW))) for c in range(n_channels)],
            op_a.eq(saturated(filt_n, DW)), op_b.eq(self.feedback),       # filt*feedback.
            NextState("WRITE"),
        )
        fsm.act("WRITE",
            buf_w.we.eq(1),
            op_a.eq(x), op_b.eq(self.dry),                                # dry*x.
            NextState("MIX"),
        )
        fsm.act("MIX",
            NextValue(acc, prod),
            op_a.eq(d), op_b.eq(self.wet),                                # wet*d.
            NextState("MIX2"),
        )
        fsm.act("MIX2",
            NextValue(acc, acc + prod),
            NextState("OUT"),
        )
        fsm.act("OUT",
            self.source.valid.eq(1),
            If(self.source.ready,
                If(ovf, NextValue(self.sat, 1)),
                If(ch == n_channels - 1, NextValue(ptr, ptr + 1)),
                NextState("IDLE"),
            ),
        )
        self.comb += [
            buf_w.adr.eq(Cat(ch, ptr)),
            buf_w.dat_w.eq(saturated(wr_val, DW)),
        ]

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
        self._delay    = CSRStorage(len(self.delay), reset=self.delay.reset.value, name="delay",
            description="Delay in frames (samples per channel), <= max_delay - 2.")
        self._feedback = CSRStorage(16, name="feedback", description="Feedback gain (signed Q1.15).")
        self._damping  = CSRStorage(15, name="damping", description="Feedback low-pass (Q0.15, 0 = off).")
        self._wet      = CSRStorage(16, reset=self.wet.reset.value, name="wet", description="Wet gain (signed Q1.15).")
        self._dry      = CSRStorage(16, reset=self.dry.reset.value, name="dry", description="Dry gain (signed Q1.15).")
        self._control  = CSRStorage(fields=[
            CSRField("bypass",    size=1, offset=0, description="Pass beats through unchanged."),
            CSRField("clear_sat", size=1, offset=1, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturation", size=1, description="Output or buffer saturated since the last clear."),
        ])
        self.comb += [
            self.delay.eq(self._delay.storage),
            self.feedback.eq(self._feedback.storage),
            self.damping.eq(self._damping.storage),
            self.wet.eq(self._wet.storage),
            self.dry.eq(self._dry.storage),
            self.bypass.eq(self._control.fields.bypass),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturation.eq(self.sat),
        ]
        if self.modulation:
            self._mod_depth = CSRStorage(len(self.mod_depth), name="mod_depth",
                description="Modulation depth in frames (delay += mod * mod_depth).")
            self.comb += self.mod_depth.eq(self._mod_depth.storage)
