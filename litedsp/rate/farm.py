#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Multi-channel DDC/resampler farm: one time-shared polyphase decimating FIR engine.

``n_channels`` separate :class:`~litedsp.filter.fir_poly.LiteDSPFIRDecimator` instances pay
for the MAC datapath (multipliers, accumulators, FSM) once per channel even though a serial
MAC is idle most of the time at typical decimated rates. The farm banks only the cheap part
per channel — the sample history lives in one channel-major RAM — and shares the expensive
part: a single serial-MAC engine (one multiplier per I/Q), one coefficient ROM and one FSM
extended with a channel index sweep the channels in round-robin TDM.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common          import check, iq_layout, scaled
from litedsp.filter.fir_poly import _pow2_ceil

# Resampler Farm -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPResamplerFarm(LiteXModule):
    """Decimate-by-R complex FIR for ``n_channels`` streams sharing one serial-MAC engine.

    Each channel behaves bit-exactly like its own
    :class:`~litedsp.filter.fir_poly.LiteDSPFIRDecimator` (same taps for all channels this
    landing; per-channel coefficient banks are a documented follow-up), but the MAC datapath,
    coefficient ROM and control FSM are instantiated once and time-shared: only the sample
    history is banked per channel, in a single channel-major RAM
    (``address = {channel, pointer}``).

    **Channel convention** (composes with :mod:`litedsp.stream.route`): the input side uses
    the :class:`~litedsp.stream.route.LiteDSPChannelMux` convention of ``n`` per-channel I/Q
    ``sinks`` with an internal TDM — the farm scans the sinks in fixed round-robin order,
    waiting on each in turn, so all channels must run at the same average rate (a stalled
    channel backpressures the farm). The output is a single channel-tagged decimated stream:
    ``iq_layout`` plus a ``channel`` payload field. It is
    :class:`~litedsp.stream.route.LiteDSPChannelDemux`-compatible — fan back out with::

        self.comb += [
            farm.source.connect(demux.sink, omit={"channel"}),
            demux.sel.eq(farm.source.channel),
        ]

    **Resources** (ECP5, implementation configuration: 4 channels x 32 taps, R=8, 16-bit,
    pipelined): 550 LUT / 189 FF / 2 BRAM / 2 DSP. Sharing retains one complex MAC engine
    instead of the 8 DSPs required by four separate two-DSP decimators; the per-channel cost is
    primarily history depth. Throughput is shared: one output costs ``n_taps`` MAC issue cycles,
    so the aggregate input rate is bounded by ``f_clk * R/self.cycles_per_output`` samples/s
    across all channels.

    ``architecture="classic"`` performs the RAM lookup, multiply, and accumulator update in one
    clock. ``architecture="pipelined"`` registers the RAM operands and then the product, draining
    both stages in two additional clocks per output. This preserves the shared two-multiplier
    engine and bit-exact output sequence while separating all three timing paths.

    Parameters
    ----------
    n_channels : int
        Number of time-shared channels (sinks). Adds only history-RAM depth per channel; the
        MAC engine, coefficient ROM and FSM are shared.
    """
    def __init__(self, n_channels=4, n_taps=32, decimation=8, data_width=16, coefficients=None,
        shift=None, with_csr=True, architecture="classic"):
        R = decimation  # Literature name.
        check(n_channels >= 1, "expected n_channels >= 1")
        check(n_taps >= 1 and R >= 1, "expected n_taps >= 1 and decimation >= 1")
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        if shift is None:
            shift = data_width - 1
        if coefficients is None:
            coefficients = [(1 << (data_width - 1)) - 1] + [0]*(n_taps - 1)
        check(len(coefficients) == n_taps, "expected len(coefficients) == n_taps")
        self.n_channels = n_channels
        self.n_taps     = n_taps
        self.decimation = R
        self.data_width = data_width
        self.architecture = architecture
        pipeline = 2*int(architecture == "pipelined")
        self.cycles_per_output = R + n_taps + 2 + pipeline  # Aggregate MAC-bound (see class doc).
        self.latency = n_taps + pipeline
        cw = max(1, bits_for(n_channels - 1))     # Channel index / tag width.
        self.sinks  = [stream.Endpoint(iq_layout(data_width)) for _ in range(n_channels)]
        self.source = stream.Endpoint(iq_layout(data_width) + [("channel", cw)])

        # # #

        # Memories.
        # ---------
        depth = _pow2_ceil(n_taps + R)                        # Per-channel history (pow2: free wrap).
        acc_w = 2*data_width + (n_taps - 1).bit_length() + 1  # Product + log2(n_taps) accumulation growth.

        crom = Memory(data_width, n_taps, init=[c & ((1 << data_width) - 1) for c in coefficients])
        mi   = Memory(data_width, depth << cw)                # Channel-major: address = {channel, ptr}.
        mq   = Memory(data_width, depth << cw)
        crp  = crom.get_port(async_read=True)
        cwp  = crom.get_port(write_capable=True)              # Runtime coefficient reload (all channels).
        wip, wqp = mi.get_port(write_capable=True), mq.get_port(write_capable=True)
        rip, rqp = mi.get_port(async_read=True),    mq.get_port(async_read=True)
        self.specials += crom, mi, mq, crp, cwp, wip, wqp, rip, rqp

        # Coefficient Reload.
        # -------------------
        # Coefficient-reload interface (write taps sequentially; default = the build-time taps).
        self.coeff_data = Signal(data_width)
        self.coeff_we   = Signal()
        self.coeff_rst  = Signal()
        cwptr = Signal(max=n_taps)
        self.comb += [cwp.adr.eq(cwptr), cwp.dat_w.eq(self.coeff_data), cwp.we.eq(self.coeff_we)]
        self.sync += If(self.coeff_rst, cwptr.eq(0)).Elif(self.coeff_we,
            If(cwptr == (n_taps - 1), cwptr.eq(0)).Else(cwptr.eq(cwptr + 1)))

        # Signals.
        # --------
        # Channels are rate-locked (round-robin TDM), so the write pointer and the position
        # within the R-sample window are shared across channels — only the RAM is banked.
        ch    = Signal(max=max(2, n_channels))        # Current channel (scan index).
        wptr  = Signal(max=depth)                     # Sample write pointer (per-channel offset).
        decim = Signal(max=R) if R > 1 else Signal()  # Position within the R-sample window.
        t     = Signal(max=n_taps + 1)                # Tap index (MAC step / coefficient address).
        radr  = Signal(max=depth)                     # History read pointer (walks back from newest).
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        ci = Signal((data_width, True))               # Signed views of the I/Q/coeff read data.
        cq = Signal((data_width, True))
        cc = Signal((data_width, True))
        sel_valid = Signal()                          # Current channel's sink, muxed.
        sel_i = Signal((data_width, True))
        sel_q = Signal((data_width, True))
        self.comb += [
            sel_valid.eq(Array([s.valid for s in self.sinks])[ch]),
            sel_i.eq(Array([s.i for s in self.sinks])[ch]),
            sel_q.eq(Array([s.q for s in self.sinks])[ch]),
            wip.adr.eq(Cat(wptr, ch)), wqp.adr.eq(Cat(wptr, ch)),
            wip.dat_w.eq(sel_i), wqp.dat_w.eq(sel_q),
            rip.adr.eq(Cat(radr, ch)), rqp.adr.eq(Cat(radr, ch)),
            crp.adr.eq(t),
            ci.eq(rip.dat_r), cq.eq(rqp.dat_r), cc.eq(crp.dat_r),
        ]

        # Scan advance: next channel; a wrap completes the TDM frame (all channels advanced
        # one sample), moving the shared write pointer / window position.
        advance = [
            If(ch == (n_channels - 1),
                NextValue(ch, 0),
                NextValue(wptr, wptr + 1),
                If(decim == (R - 1),
                    NextValue(decim, 0),
                ).Else(
                    NextValue(decim, decim + 1),
                ),
            ).Else(
                NextValue(ch, ch + 1),
            )
        ]

        # FSM.
        # ----
        self.fsm = fsm = FSM(reset_state="LOAD")
        # LOAD: store the current channel's sample; the R-th sample of its window kicks off a
        # MAC pass for that channel (other sinks stay backpressured until its output is out).
        fsm.act("LOAD",
            Case(ch, {k: self.sinks[k].ready.eq(1) for k in range(n_channels)}),
            If(sel_valid,
                wip.we.eq(1), wqp.we.eq(1),
                If(decim == (R - 1),
                    NextValue(t, 0),
                    NextValue(acc_i, 0), NextValue(acc_q, 0),
                    NextValue(radr, wptr),       # Newest sample (just written at {ch, wptr}).
                    NextState("MAC"),
                ).Else(
                    *advance,
                )
            )
        )
        # MAC: one tap per cycle; the explicit pipeline registers the distributed-RAM operands,
        # then the product, and consumes both trailing stages in two drain clocks.
        if architecture == "classic":
            fsm.act("MAC",
                NextValue(acc_i, acc_i + ci*cc),
                NextValue(acc_q, acc_q + cq*cc),
                NextValue(radr, radr - 1),
                NextValue(t, t + 1),
                If(t == (n_taps - 1), NextState("EMIT")),
            )
        else:
            operand_i = Signal((data_width, True))
            operand_q = Signal((data_width, True))
            operand_c = Signal((data_width, True))
            operand_valid = Signal()
            prod_i = Signal((2*data_width, True))
            prod_q = Signal((2*data_width, True))
            prod_valid = Signal()
            fsm.act("MAC",
                NextValue(operand_i, ci),
                NextValue(operand_q, cq),
                NextValue(operand_c, cc),
                NextValue(operand_valid, 1),
                NextValue(prod_i, operand_i*operand_c),
                NextValue(prod_q, operand_q*operand_c),
                NextValue(prod_valid, operand_valid),
                If(prod_valid,
                    NextValue(acc_i, acc_i + prod_i),
                    NextValue(acc_q, acc_q + prod_q),
                ),
                NextValue(radr, radr - 1),
                NextValue(t, t + 1),
                If(t == (n_taps - 1), NextState("MAC_DRAIN_PRODUCT")),
            )
            fsm.act("MAC_DRAIN_PRODUCT",
                NextValue(prod_i, operand_i*operand_c),
                NextValue(prod_q, operand_q*operand_c),
                NextValue(prod_valid, operand_valid),
                If(prod_valid,
                    NextValue(acc_i, acc_i + prod_i),
                    NextValue(acc_q, acc_q + prod_q),
                ),
                NextValue(operand_valid, 0),
                NextState("MAC_DRAIN_ACC"),
            )
            fsm.act("MAC_DRAIN_ACC",
                If(prod_valid,
                    NextValue(acc_i, acc_i + prod_i),
                    NextValue(acc_q, acc_q + prod_q),
                ),
                NextValue(prod_valid, 0),
                NextState("EMIT"),
            )
        out_i, _ = scaled(acc_i, shift, data_width)
        out_q, _ = scaled(acc_q, shift, data_width)
        # EMIT: present the channel-tagged result; the farm stays stalled until it is accepted.
        fsm.act("EMIT",
            self.source.valid.eq(1),
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            self.source.channel.eq(ch),
            If(self.source.ready,
                *advance,
                NextState("LOAD"),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("taps",     size=16, description="FIR taps N."),
            CSRField("rate",     size=8,  description="Decimation factor R."),
            CSRField("channels", size=8,  description="Time-shared channels."),
        ])
        self._coeff_rst = CSRStorage(1, name="coeff_reset",
            description="Reset the coefficient write pointer to tap 0 (write to strobe).")
        self._coeff = CSRStorage(self.data_width, name="coeff",
            description="Write the next FIR coefficient (auto-incrementing tap index, shared by all channels).")
        self.comb += [
            self._config.fields.taps.eq(self.n_taps),
            self._config.fields.rate.eq(self.decimation),
            self._config.fields.channels.eq(self.n_channels),
            self.coeff_rst.eq(self._coeff_rst.re),
            self.coeff_data.eq(self._coeff.storage),
            self.coeff_we.eq(self._coeff.re),
        ]
