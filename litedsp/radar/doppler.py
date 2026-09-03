#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Doppler processing: per-range-bin FFT across the pulses of a CPI, magnitude or power out."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common             import check, iq_layout, real_layout
from litedsp.analysis.window    import LiteDSPWindow
from litedsp.analysis.fft       import LiteDSPFFT
from litedsp.analysis.magnitude import LiteDSPMagnitude
from litedsp.analysis.reorder   import LiteDSPBitReverse
from litedsp.radar.waveform     import WINDOWS

MAGNITUDES = ("approx", "power")

# Doppler Processor --------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDopplerProcessor(LiteXModule):
    """Slow-time columns (``n_pulses`` beats per range bin) to range-Doppler map rows.

    Composite of :class:`LiteDSPWindow` (omitted for ``window="rect"``), a scaled radix-2
    :class:`LiteDSPFFT` over the pulses, the magnitude stage (``"approx"``: alpha-max-beta-min,
    ``data_width + 1`` bits; ``"power"``: ``i^2 + q^2``, ``2*data_width + 1`` bits) and
    :class:`LiteDSPBitReverse`, so each output frame holds the ``n_pulses`` Doppler bins of one
    range bin in natural FFT order (bins ``>= n_pulses/2`` are negative velocities). Frame
    alignment counts from reset (the window/FFT convention); a ``first``/``last`` arriving at
    the wrong position sets the sticky ``frame_error``. ``latency = None`` (a column is
    buffered in the reorder).
    """
    def __init__(self, n_pulses=16, data_width=16, window="hann", magnitude="approx",
        twiddle_width=16, beta_shift=2, with_csr=True):
        check(n_pulses >= 2 and (n_pulses & (n_pulses - 1)) == 0, "expected n_pulses a power of two >= 2")
        check(window in WINDOWS, f"expected window in {WINDOWS}")
        check(magnitude in MAGNITUDES, f"expected magnitude in {MAGNITUDES}")
        self.n_pulses   = n_pulses
        self.data_width = data_width
        self.window_kind = window
        self.magnitude  = magnitude
        self.out_width  = data_width + 1 if magnitude == "approx" else 2*data_width + 1
        self.latency    = None
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(real_layout(self.out_width))
        self.clear       = Signal()
        self.frame_error = Signal()

        # # #

        # Input frame monitor (counts from reset like the window and the FFT).
        # ---------------------------------------------------------------------
        xfer_in = Signal()
        pos     = Signal(max=n_pulses)
        self.comb += xfer_in.eq(self.sink.valid & self.sink.ready)
        self.sync += [
            If(xfer_in,
                If(pos == n_pulses - 1, pos.eq(0)).Else(pos.eq(pos + 1)),
                If(self.clear,
                    self.frame_error.eq(0),
                ).Elif((self.sink.first != (pos == 0)) | (self.sink.last != (pos == n_pulses - 1)),
                    self.frame_error.eq(1),
                ),
            ).Elif(self.clear,
                self.frame_error.eq(0),
            ),
        ]

        # Window -> FFT -> magnitude -> natural order.
        # --------------------------------------------
        self.fft = LiteDSPFFT(n_pulses, data_width=data_width, twiddle_width=twiddle_width,
            scaling="scaled", with_csr=False)
        if window == "rect":
            self.comb += self.sink.connect(self.fft.sink)
        else:
            self.window = LiteDSPWindow(n_pulses, data_width=data_width, window=window, with_csr=False)
            self.comb += [self.sink.connect(self.window.sink), self.window.source.connect(self.fft.sink)]
        self.reorder = LiteDSPBitReverse(N=n_pulses, layout=real_layout(self.out_width),
            fft_latency=self.fft.latency, with_csr=False)
        if magnitude == "approx":
            self.mag = LiteDSPMagnitude(data_width=data_width, beta_shift=beta_shift, method="approx",
                with_csr=False)
            self.comb += [
                self.fft.source.connect(self.mag.sink, omit={"first", "last"}),
                self.mag.source.connect(self.reorder.sink, omit={"first", "last"}),
            ]
        else:
            adv = Signal()
            pi  = Signal(2*data_width)                                 # i*i (unsigned).
            pq  = Signal(2*data_width)
            self.comb += [
                adv.eq(self.reorder.sink.ready | ~self.reorder.sink.valid),
                self.fft.source.ready.eq(adv),
                pi.eq(self.fft.source.i*self.fft.source.i),
                pq.eq(self.fft.source.q*self.fft.source.q),
            ]
            self.sync += If(adv,
                self.reorder.sink.valid.eq(self.fft.source.valid),
                self.reorder.sink.data.eq(pi + pq),
            )
        self.comb += self.reorder.source.connect(self.source)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n_pulses",  size=16, offset=0,  description="Doppler bins (pulses per CPI)."),
            CSRField("out_width", size=8,  offset=16, description="Output cell width."),
            CSRField("power",     size=1,  offset=24, description="1: power cells, 0: magnitude cells."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the frame error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("frame_error", size=1, offset=0, description="Sticky: input framing did not match n_pulses."),
        ])
        self.comb += [
            self._config.fields.n_pulses.eq(self.n_pulses),
            self._config.fields.out_width.eq(self.out_width),
            self._config.fields.power.eq(int(self.magnitude == "power")),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.frame_error.eq(self.frame_error),
        ]
