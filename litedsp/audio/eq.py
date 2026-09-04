#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, tdm_layout, tdm_channel, tdm_channel_bits, rounded, saturated

# Audio Equalizer ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAudioEQ(LiteXModule):
    """Multi-band, multi-channel parametric equalizer: a time-multiplexed biquad engine.

    ``n_bands`` cascaded biquads per channel of the TDM stream share one multiplier: per
    beat the engine runs the bands in sequence (8 cycles each) from state and coefficient
    RAMs, so ``cycles_per_sample = 8*n_bands + 2`` (a 3-band stereo EQ at 48 kHz needs a
    2.5 MHz clock). Each section is direct-form I with a full-precision accumulator and
    first- (``error_feedback=1``, default) or second-order error feedback of the rounding
    error, i.e. the noise transfer (1 - z^-1)^k cancels the huge low-frequency round-off gain
    of low-Q/low-frequency biquads (a 40 Hz shelf at 48 kHz has poles at r = 0.997) while the
    state stays narrow (x1, x2, y1, y2 at ``data_width``, e at ``frac_bits``). Coefficients are
    signed Q(coeff_width-frac_bits).frac_bits (Q4.28 by default: pole-radius resolution 4e-9,
    what 20-50 Hz bands need) per band, shared by the channels; ``sections`` seeds them
    (dicts from :func:`litedsp.filter.design.biquad_sos_quantize`, default passthrough).

    Runtime reload: write ``coeff_index`` (``8*band + k``, k = 0..4 for b0, b1, b2, a1, a2)
    then ``coeff_value`` (auto-incrementing) into a shadow table, and pulse ``commit``: the
    engine copies shadow -> active between beats, so no sample sees mixed coefficients.
    ``band_enable`` bits bypass individual bands (state kept fresh for a click-free
    re-enable); ``bypass`` passes beats through (2 cycles). Sticky ``sat`` on output
    saturation. Latency ``8*n_bands + 1`` cycles.

    Parameters
    ----------
    n_bands : int
        Cascaded biquad sections per channel.
    n_channels : int
        Channels in the TDM frame (1 = mono, real layout).
    coeff_width, frac_bits : int
        Coefficient format (signed, 1.0 = 2**frac_bits).
    sections : list
        Initial coefficients: ``n_bands`` dicts ``{b0, b1, b2, a1, a2}`` (default passthrough).
    error_feedback : int
        Order of the error feedback (0, 1 or 2).
    """
    def __init__(self, data_width=24, n_bands=3, n_channels=2, coeff_width=32, frac_bits=28,
        sections=None, error_feedback=1, with_csr=True):
        check(data_width >= 8, "expected data_width >= 8")
        check(n_bands >= 1, "expected n_bands >= 1")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(0 < frac_bits < coeff_width <= 64, "expected 0 < frac_bits < coeff_width <= 64")
        check(error_feedback in (0, 1, 2), "expected error_feedback in (0, 1, 2)")
        if sections is None:
            sections = [{"b0": 1 << frac_bits, "b1": 0, "b2": 0, "a1": 0, "a2": 0}]*n_bands
        check(len(sections) == n_bands, "expected n_bands coefficient sections")
        self.data_width     = data_width
        self.n_bands        = n_bands
        self.n_channels     = n_channels
        self.coeff_width    = coeff_width
        self.frac_bits      = frac_bits
        self.error_feedback = error_feedback
        self.sections       = sections
        self.cycles_per_sample = 8*n_bands + 2
        self.latency        = 8*n_bands + 1
        self.sink   = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.band_enable    = Signal(n_bands, reset=(1 << n_bands) - 1)
        self.bypass         = Signal()
        self.coeff_index    = Signal(max=8*n_bands)
        self.coeff_value    = Signal(coeff_width)
        self.coeff_we       = Signal()
        self.coeff_commit   = Signal()
        self.commit_pending = Signal()
        self.clear_sat      = Signal()
        self.sat            = Signal()

        # # #

        F, CW, DW = frac_bits, coeff_width, data_width
        n_entries = max(2, n_channels*n_bands)
        cmask     = (1 << CW) - 1
        init = []
        for s in sections:
            init += [s["b0"] & cmask, s["b1"] & cmask, s["b2"] & cmask, s["a1"] & cmask,
                     s["a2"] & cmask, 0, 0, 0]

        # Coefficient RAMs (active: engine reads; shadow: host writes) and state RAM.
        # -------------------------------------------------------------------------
        active = Memory(CW, 8*n_bands, init=init)
        shadow = Memory(CW, 8*n_bands, init=init)
        act_rd = active.get_port(async_read=True)
        act_wr = active.get_port(write_capable=True)
        sha_rd = shadow.get_port(async_read=True)
        sha_wr = shadow.get_port(write_capable=True)
        SW     = 4*DW + 2*F
        state  = Memory(SW, n_entries)
        st_rd  = state.get_port(async_read=True)
        st_wr  = state.get_port(write_capable=True)
        self.specials += active, shadow, act_rd, act_wr, sha_rd, sha_wr, state, st_rd, st_wr

        # Host shadow writes (auto-incrementing index) and commit request.
        # ----------------------------------------------------------------
        self.comb += [sha_wr.adr.eq(self.coeff_index), sha_wr.dat_w.eq(self.coeff_value),
                      sha_wr.we.eq(self.coeff_we)]
        self.sync += [
            If(self.coeff_commit, self.commit_pending.eq(1)),
        ]

        # Engine.
        # -------
        x_in  = Signal((DW, True))                                  # Band input / final output.
        en_lat = Signal(n_bands)                                    # band_enable at acceptance.
        ch    = Signal(tdm_channel_bits(n_channels))
        first, last = Signal(), Signal()
        band  = Signal(max=max(2, n_bands))
        step  = Signal(3)
        kidx  = Signal(3)
        copy  = Signal(max=8*n_bands + 1)
        x1, x2 = Signal((DW, True)), Signal((DW, True))
        y1, y2 = Signal((DW, True)), Signal((DW, True))
        e1, e2 = Signal((F, True)), Signal((F, True))
        self.comb += [
            st_rd.adr.eq(ch*n_bands + band),
            x1.eq(st_rd.dat_r[0:DW]), x2.eq(st_rd.dat_r[DW:2*DW]),
            y1.eq(st_rd.dat_r[2*DW:3*DW]), y2.eq(st_rd.dat_r[3*DW:4*DW]),
            e1.eq(st_rd.dat_r[4*DW:4*DW + F]), e2.eq(st_rd.dat_r[4*DW + F:4*DW + 2*F]),
            act_rd.adr.eq(Cat(kidx, band)),
        ]
        AW    = DW + CW + 3
        acc   = Signal((AW, True))
        op_x  = Signal((DW, True))
        coef  = Signal((CW, True))                                  # Signed view of the RAM word.
        prod  = Signal((DW + CW, True))
        prod_neg = Signal()
        acc_add  = Signal()
        fb    = Signal((F + 3, True))
        if error_feedback == 1:
            self.comb += fb.eq(e1)
        elif error_feedback == 2:
            self.comb += fb.eq(2*e1 - e2)
        self.comb += [
            op_x.eq(Array([x_in, x1, x2, y1, y2])[kidx]),
            coef.eq(act_rd.dat_r),
        ]
        y_r   = Signal((AW - F, True))
        y_out = Signal((DW, True))
        err   = Signal((F, True))
        ovf   = Signal()
        enabled = Signal()
        self.comb += [
            y_r.eq(rounded(acc, F)),
            y_out.eq(saturated(y_r, DW)),
            err.eq(acc - (y_r << F)),
            ovf.eq(y_r != y_out),
            enabled.eq(Array([en_lat[k] for k in range(n_bands)])[band]),
        ]
        y_band = Signal((DW, True))                                 # Band output (or passthrough).
        err_w  = Signal((F, True))                                  # Error written back.
        self.comb += [
            y_band.eq(Mux(enabled, y_out, x_in)),
            err_w.eq(Mux(enabled, err, 0)),
        ]
        self.sync += [
            prod.eq(op_x*coef),                                      # Issued with kidx ...
            prod_neg.eq(kidx >= 3),                                  # ... a1/a2 are subtracted.
        ]
        self.comb += acc_add.eq((step >= 1) & (step <= 5))           # Accumulate products 0..4.

        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(self.commit_pending,
                NextValue(copy, 0),
                NextState("COPY"),
            ).Else(
                self.sink.ready.eq(1),
                If(self.sink.valid,
                    NextValue(x_in, self.sink.data),
                    NextValue(en_lat, self.band_enable),
                    NextValue(ch, tdm_channel(self.sink)),
                    NextValue(first, self.sink.first),
                    NextValue(last, self.sink.last),
                    NextValue(band, 0),
                    NextValue(step, 0),
                    NextValue(kidx, 0),
                    If(self.bypass, NextState("OUT")).Else(NextState("BAND")),
                ),
            ),
        )
        # Band schedule: step 0 loads acc with the error feedback and issues product 0 (kidx 0,
        # registered for step 1); steps 1..4 issue products 1..4 while steps 1..5 accumulate
        # the product issued one step earlier; step 6 settles; step 7 rounds, writes the state
        # and moves to the next band.
        fsm.act("BAND",
            NextValue(step, step + 1),
            If(step == 0,
                NextValue(acc, fb),
            ),
            If(step <= 3,
                NextValue(kidx, kidx + 1),
            ),
            If(acc_add,
                NextValue(acc, Mux(prod_neg, acc - prod, acc + prod)),
            ),
            If(step == 7,
                st_wr.we.eq(1),
                NextValue(x_in, y_band),
                NextValue(kidx, 0),
                If(enabled & ovf, NextValue(self.sat, 1)),
                If(band == n_bands - 1,
                    NextState("OUT"),
                ).Else(
                    NextValue(band, band + 1),
                ),
            ),
        )
        fsm.act("OUT",
            self.source.valid.eq(1),
            If(self.source.ready, NextState("IDLE")),
        )
        fsm.act("COPY",
            act_wr.we.eq(1),
            NextValue(copy, copy + 1),
            If(copy == 8*n_bands - 1,
                NextValue(self.commit_pending, 0),
                NextState("IDLE"),
            ),
        )
        self.comb += [
            st_wr.adr.eq(st_rd.adr),
            # Explicitly sized fields: a widened Mux would shift the following slots.
            st_wr.dat_w.eq(Cat(x_in, x1, y_band, y1, err_w, e1)),
            sha_rd.adr.eq(copy),
            act_wr.adr.eq(copy),
            act_wr.dat_w.eq(sha_rd.dat_r),
            self.source.data.eq(x_in),
            self.source.first.eq(first),
            self.source.last.eq(last),
        ]
        if n_channels > 1:
            self.comb += self.source.channel.eq(ch)
        self.sync += If(self.clear_sat, self.sat.eq(0))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n_bands",        size=8,  offset=0,  description="Cascaded sections per channel."),
            CSRField("n_channels",     size=8,  offset=8,  description="Channels in the TDM frame."),
            CSRField("coeff_width",    size=8,  offset=16, description="Coefficient width in bits."),
            CSRField("frac_bits",      size=8,  offset=24, description="Coefficient fractional bits."),
        ])
        self._coeff_index = CSRStorage(self.coeff_index.nbits, name="coeff_index",
            description="Shadow coefficient address: 8*band + k (k = 0..4: b0, b1, b2, a1, a2); "
                        "auto-increments on value writes.")
        self._coeff_value = CSRStorage(self.coeff_width, name="coeff_value",
            description="Shadow coefficient value (signed Q(coeff_width-frac_bits).frac_bits); "
                        "writing stores and increments the index.")
        self._band_enable = CSRStorage(self.n_bands, reset=(1 << self.n_bands) - 1,
                                       name="band_enable",
            description="Per-band enable mask (a disabled band passes its input through).")
        self._control = CSRStorage(fields=[
            CSRField("commit",    size=1, offset=0, pulse=True, description="Copy the shadow coefficients into the active set."),
            CSRField("bypass",    size=1, offset=1, description="Pass beats through unchanged."),
            CSRField("clear_sat", size=1, offset=2, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("commit_pending", size=1, offset=0, description="A commit is waiting for the engine."),
            CSRField("saturation",     size=1, offset=1, description="A band output saturated since the last clear."),
        ])
        index_next = Signal.like(self.coeff_index)
        self.comb += [
            self._config.fields.n_bands.eq(self.n_bands),
            self._config.fields.n_channels.eq(self.n_channels),
            self._config.fields.coeff_width.eq(self.coeff_width),
            self._config.fields.frac_bits.eq(self.frac_bits),
            self.coeff_index.eq(self._coeff_index.storage),
            self.coeff_value.eq(self._coeff_value.storage),
            self.coeff_we.eq(self._coeff_value.re),
            self.band_enable.eq(self._band_enable.storage),
            self.coeff_commit.eq(self._control.fields.commit),
            self.bypass.eq(self._control.fields.bypass),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.commit_pending.eq(self.commit_pending),
            self._status.fields.saturation.eq(self.sat),
        ]
        # Auto-increment the index after each value write (wraps at the table end).
        self.sync += If(self._coeff_value.re,
            self._coeff_index.storage.eq(Mux(self.coeff_index == 8*self.n_bands - 1, 0,
                                             self.coeff_index + 1)),
        )
