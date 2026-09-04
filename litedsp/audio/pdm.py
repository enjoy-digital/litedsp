#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""1-bit audio I/O: an error-feedback sigma-delta modulator, a PDM DAC built on it and a PDM
microphone receiver (clocked bitstream interface + sinc decimators + DC blocking + optional droop
compensation) producing a channel-tagged TDM stream."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common             import check, real_layout, tdm_layout, saturated
from litedsp.filter.bitstream   import LiteDSPBitstreamDecimator
from litedsp.filter.dc_blocker  import LiteDSPDCBlocker
from litedsp.filter.fir         import LiteDSPFIRFilter, LiteDSPFIRCoefficients
from litedsp.filter.design      import cic_comp_coefficients
from litedsp.frontend.converter import LiteDSPBitstreamInterface
from litedsp.stream.route       import LiteDSPTDMMux, LiteDSPTDMDemux

# Sigma-Delta Modulator ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSigmaDeltaModulator(LiteXModule):
    """Error-feedback sigma-delta modulator: ``real_layout`` samples to a 1-bit stream at
    ``interpolation`` bits per sample (zero-order hold).

    Per output bit with the held input ``x``: ``u = x + e1`` (order 1) or ``u = x + 2*e1 - e2``
    (order 2); ``bit = (u >= 0)``; ``e = u - (bit ? +FS : -FS)`` with ``FS = 2**(data_width -
    1)``, the error state saturated to ``data_width + 2`` bits. The quantization noise is shaped
    by ``(1 - z**-1)**order``. Keep the input below about -3 dBFS for the second-order loop to
    stay in its stable range. Latency 1 (first bit), rate ``(interpolation, 1)``.
    """
    def __init__(self, data_width=24, interpolation=64, order=2, with_csr=True):
        check(data_width >= 8, "expected data_width >= 8")
        check(interpolation >= 1, "expected interpolation >= 1")
        check(order in (1, 2), "expected order in (1, 2)")
        self.data_width    = data_width
        self.interpolation = interpolation
        self.order         = order
        self.latency       = 1
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([("data", 1)])

        # # #

        FS = 1 << (data_width - 1)
        EW = data_width + 2                                                # Error state width.
        adv, first, active, xfer = Signal(), Signal(), Signal(), Signal()
        count  = Signal(max=max(2, interpolation))
        x_hold = Signal((data_width, True))
        x_cur  = Signal((data_width, True))
        e1     = Signal((EW, True))
        e2     = Signal((EW, True))
        u      = Signal((data_width + 5, True))                            # x + 2 e1 - e2.
        e      = Signal((data_width + 5, True))
        bit    = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            first.eq(count == 0),
            self.sink.ready.eq(adv & first),
            active.eq(~first | self.sink.valid),                           # A bit is produced.
            xfer.eq(adv & active),
            x_cur.eq(Mux(first, self.sink.data, x_hold)),
            u.eq(x_cur + e1) if order == 1 else u.eq(x_cur + (e1 << 1) - e2),
            bit.eq(~u[-1]),
            e.eq(u - Mux(bit, FS, -FS)),
        ]
        self.sync += [
            If(adv, self.source.valid.eq(active), self.source.data.eq(bit)),
            If(xfer,
                e1.eq(saturated(e, EW)), e2.eq(e1),
                If(first, x_hold.eq(self.sink.data)),
                count.eq(Mux(count == interpolation - 1, 0, count + 1)),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("interpolation", size=16, offset=0,  description="Bits per input sample."),
            CSRField("order",         size=2,  offset=16, description="Noise-shaping order."),
        ])
        self.comb += [
            self._config.fields.interpolation.eq(self.interpolation),
            self._config.fields.order.eq(self.order),
        ]

# Sigma-Delta DAC ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSigmaDeltaDAC(LiteXModule):
    """PDM DAC: a TDM (or mono) sink feeding one :class:`LiteDSPSigmaDeltaModulator` per channel,
    whose bits are clocked out on ``pdm_out[c]`` at ``sys_clk / clk_div`` (``pdm_clk`` pin, the
    bit changes on its falling edge). Once streaming has started, a tick with no bit available
    (input starved) repeats the last bit and sets the sticky ``underrun`` flag.
    Sink-only (``latency = None``); feed it at
    ``sys_clk / (clk_div * interpolation)`` frames per second.
    """
    def __init__(self, data_width=24, n_channels=1, interpolation=64, order=2, clk_div=16,
        with_csr=True):
        check(n_channels >= 1, "expected n_channels >= 1")
        check(clk_div >= 2 and clk_div % 2 == 0, "expected an even clk_div >= 2")
        self.data_width    = data_width
        self.n_channels    = n_channels
        self.interpolation = interpolation
        self.order         = order
        self.clk_div       = clk_div
        self.latency       = None
        self.sink     = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.pdm_out  = Signal(n_channels)                                  # Pins.
        self.pdm_clk  = Signal()
        self.underrun = Signal()
        self.clear    = Signal()

        # # #

        # Bit clock.
        # ----------
        div  = Signal(max=clk_div)
        tick = Signal()
        self.sync += If(div == clk_div - 1, div.eq(0)).Else(div.eq(div + 1))
        self.comb += [
            self.pdm_clk.eq(div < clk_div//2),
            tick.eq(div == clk_div//2 - 1),                                 # Last high cycle.
        ]

        # Per-channel modulators.
        # -----------------------
        self.demux = LiteDSPTDMDemux(n_channels=n_channels, data_width=data_width, with_csr=False)
        self.comb += self.sink.connect(self.demux.sink)
        started = Signal()                                                  # First bit seen.
        starved = []
        self.modulators = []
        for c in range(n_channels):
            mod = LiteDSPSigmaDeltaModulator(data_width=data_width, interpolation=interpolation,
                order=order, with_csr=False)
            self.add_module(name=f"modulator{c}", module=mod)
            self.modulators.append(mod)
            self.comb += [
                self.demux.sources[c].connect(mod.sink),
                mod.source.ready.eq(tick),
            ]
            self.sync += [
                If(tick & mod.source.valid, self.pdm_out[c].eq(mod.source.data), started.eq(1)),
            ]
            starved.append(tick & started & ~mod.source.valid)
        self.sync += If(self.clear, self.underrun.eq(0)).Elif(reduce(lambda a, b: a | b, starved),
            self.underrun.eq(1))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the underrun flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("underrun", size=1, offset=0, description="Sticky: a bit tick found no sample."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_channels",    size=4,  offset=0,  description="Channels."),
            CSRField("clk_div",       size=8,  offset=4,  description="sys_clk / pdm_clk."),
            CSRField("interpolation", size=16, offset=12, description="Bits per sample."),
        ])
        self.comb += [
            self.clear.eq(self._control.fields.clear),
            self._status.fields.underrun.eq(self.underrun),
            self._config.fields.n_channels.eq(self.n_channels),
            self._config.fields.clk_div.eq(self.clk_div),
            self._config.fields.interpolation.eq(self.interpolation),
        ]

# PDM Receiver -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPDMReceiver(LiteXModule):
    """PDM microphone receiver: :class:`LiteDSPBitstreamInterface` (``mclk`` out at ``sys_clk /
    clk_div``, ``mdat`` in; ``dual_edge`` puts two channels on one line, the stereo-microphone
    L/R select) feeding one :class:`LiteDSPBitstreamDecimator` (sinc^N, ``decimation``) per
    channel, an optional mono :class:`LiteDSPDCBlocker` (``dc_pole_shift``, 8 fractional bits)
    and an optional CIC droop-compensation :class:`LiteDSPFIRFilter` (``n_comp_taps``, serial
    MAC), interleaved by a :class:`LiteDSPTDMMux` into a channel-tagged TDM source at ``sys_clk
    / (clk_div * decimation)`` frames per second. Source-only (``latency = None``); the
    interface's sticky ``overrun`` flags a bit dropped by back-pressure.
    """
    def __init__(self, data_width=24, n_channels=2, decimation=64, n_stages=4, clk_div=16,
        dual_edge=True, with_dc_blocker=True, dc_pole_shift=10, with_compensation=False,
        n_comp_taps=15, with_csr=True):
        check(n_channels >= 1, "expected n_channels >= 1")
        check(not dual_edge or n_channels % 2 == 0, "dual_edge needs an even n_channels")
        check(n_comp_taps % 2 == 1, "expected an odd n_comp_taps")
        n_lines = n_channels//2 if dual_edge else n_channels
        self.data_width        = data_width
        self.n_channels        = n_channels
        self.decimation        = decimation
        self.n_stages          = n_stages
        self.clk_div           = clk_div
        self.with_dc_blocker   = with_dc_blocker
        self.dc_pole_shift     = dc_pole_shift
        self.with_compensation = with_compensation
        self.comp_coefficients = (
            cic_comp_coefficients(n_comp_taps, decimation, n_stages, 1, data_width)
                                  if with_compensation else None)
        self.latency = None
        self.source  = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.mclk    = Signal()                                             # Pins.
        self.mdat    = Signal(n_lines)
        self.overrun = Signal()
        self.clear   = Signal()

        # # #

        self.interface = LiteDSPBitstreamInterface(clock_div=clk_div, n_channels=n_channels,
            dual_edge=dual_edge)
        self.mux = LiteDSPTDMMux(n_channels=n_channels, data_width=data_width, with_csr=False)
        self.comb += [
            self.mclk.eq(self.interface.mclk),
            self.interface.mdat.eq(self.mdat),
            self.interface.clear.eq(self.clear),
            self.overrun.eq(self.interface.overrun),
            self.mux.source.connect(self.source),
        ]
        if with_compensation:
            self.coefficients = LiteDSPFIRCoefficients(n_taps=n_comp_taps, data_width=data_width,
                coefficients=self.comp_coefficients, with_csr=False)
        for c in range(n_channels):
            dec = LiteDSPBitstreamDecimator(data_width=data_width, decimation=decimation,
                n_stages=n_stages, with_csr=False)
            self.add_module(name=f"decimator{c}", module=dec)
            self.comb += self.interface.sources[c].connect(dec.sink)
            last = dec.source
            if with_dc_blocker:
                dcb = LiteDSPDCBlocker(data_width=data_width, pole_shift=dc_pole_shift,
                    precision_bits=8, iq=False, with_csr=False)
                self.add_module(name=f"dc_blocker{c}", module=dcb)
                self.comb += last.connect(dcb.sink)
                last = dcb.source
            if with_compensation:
                fir = LiteDSPFIRFilter(n_taps=n_comp_taps, data_width=data_width, symmetric=False,
                    architecture="mac", n_macs=1)
                self.add_module(name=f"compensation{c}", module=fir)
                self.comb += [fir.coeffs[k].eq(self.coefficients.values[k])
                                                                        for k in range(n_comp_taps)]
                self.comb += last.connect(fir.sink)
                last = fir.source
            self.comb += last.connect(self.mux.sinks[c])

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the overrun flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("overrun", size=1, offset=0, description="Sticky: a bit was dropped (back-pressure)."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_channels",   size=4,  offset=0,  description="Channels."),
            CSRField("clk_div",      size=8,  offset=4,  description="sys_clk / mclk."),
            CSRField("decimation",   size=16, offset=12, description="Bits per output sample."),
            CSRField("dc_blocker",   size=1,  offset=28, description="DC blocker present."),
            CSRField("compensation", size=1,  offset=29, description="Droop compensation present."),
        ])
        self.comb += [
            self.clear.eq(self._control.fields.clear),
            self._status.fields.overrun.eq(self.overrun),
            self._config.fields.n_channels.eq(self.n_channels),
            self._config.fields.clk_div.eq(self.clk_div),
            self._config.fields.decimation.eq(self.decimation),
            self._config.fields.dc_blocker.eq(int(self.with_dc_blocker)),
            self._config.fields.compensation.eq(int(self.with_compensation)),
        ]
