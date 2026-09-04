#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pulse compression: the complex matched filter of the transmitted chirp."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import check, iq_layout, saturated
from litedsp.filter.fir     import LiteDSPFIRFilterComplex
from litedsp.radar.waveform import pulse_compressor_taps, WINDOWS

# Pulse Compressor ---------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPulseCompressor(LiteXModule):
    """Matched filter for the linear-FM pulse of :class:`~litedsp.generation.source.LiteDSPChirp`
    (``pulse_len`` samples sweeping ``bandwidth`` cycles/sample), i.e. the correlation of the
    received I/Q stream with the conjugate time-reversed (optionally tapered) reference.

    The complex-tap convolution runs on two :class:`~litedsp.filter.fir.LiteDSPFIRFilterComplex`
    in lock-step (real taps ``Re h`` and ``Im h`` applied to I and Q) and is recombined as
    ``y = (re.i - im.q) + j (re.q + im.i)`` with saturation. ``shift`` rescales the
    ``pulse_len``-fold coherent gain (default ``data_width - 1 + log2(pulse_len)``: a full-scale
    echo peaks near full scale). ``first``/``last`` are re-aligned by ``pulse_len - 1`` beats so
    range bin ``r`` of a pulse sits at position ``r`` of the output frame (the first
    ``pulse_len - 1`` positions of a frame carry the fold-over of the previous one). Latency
    ``fir.latency + 1`` (``None``, variable, with the serial ``mac`` architecture).

    Parameters
    ----------
    window : str
        Taper of the reference (``rect``, ``hann``, ``hamming``, ``blackman``): lower range
        sidelobes for a wider main lobe.
    fir_architecture, n_macs : str, int
        Forwarded to the two FIR filters (``mac`` shares ``n_macs`` multipliers).
    """
    def __init__(self, pulse_len=16, bandwidth=0.5, data_width=16, window="rect", shift=None,
        phase_bits=32, lut_depth=1024, fir_architecture="classic", n_macs=4, with_csr=True):
        check(pulse_len >= 2, "expected pulse_len >= 2")
        check(0.0 < bandwidth <= 1.0, "expected 0 < bandwidth <= 1")
        check(window in WINDOWS, f"expected window in {WINDOWS}")
        if shift is None:
            shift = (data_width - 1) + (pulse_len - 1).bit_length()
        check(0 <= shift <= 2*data_width + pulse_len.bit_length(), "expected a non-negative shift")
        re_taps, im_taps = pulse_compressor_taps(pulse_len, bandwidth, data_width, window,
                                                 phase_bits, lut_depth)
        self.pulse_len  = pulse_len
        self.data_width = data_width
        self.shift      = shift
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.clear     = Signal()
        self.saturated = Signal()
        self.fir_re = LiteDSPFIRFilterComplex(n_taps=pulse_len, data_width=data_width,
                                              coefficients=re_taps,
            shift=shift, with_csr=False, architecture=fir_architecture, n_macs=n_macs)
        self.fir_im = LiteDSPFIRFilterComplex(n_taps=pulse_len, data_width=data_width,
                                              coefficients=im_taps,
            shift=shift, with_csr=False, architecture=fir_architecture, n_macs=n_macs)
        fir_latency  = self.fir_re.latency                                 # None for 'mac'.
        self.latency = None if fir_latency is None else fir_latency + 1

        # # #

        # Lock-stepped filters fed from one sink; the framing tags bypass them.
        # ---------------------------------------------------------------------
        adv, xfer_in, xfer_out = Signal(), Signal(), Signal()
        # Carries first/last.
        self.tags = tags = stream.SyncFIFO([("pad", 1)], (fir_latency or pulse_len) + 8)
        sr = [Signal(2, name=f"tag_sr{k}") for k in range(pulse_len - 1)]  # Re-align by P-1.
        self.comb += [
            self.sink.ready.eq(self.fir_re.sink.ready & self.fir_im.sink.ready & tags.sink.ready),
            xfer_in.eq(self.sink.valid & self.sink.ready),
            self.fir_re.sink.valid.eq(xfer_in), self.fir_im.sink.valid.eq(xfer_in),
            self.fir_re.sink.i.eq(self.sink.i), self.fir_re.sink.q.eq(self.sink.q),
            self.fir_im.sink.i.eq(self.sink.i), self.fir_im.sink.q.eq(self.sink.q),
            tags.sink.valid.eq(xfer_in),
            tags.sink.first.eq(sr[-1][0] if sr else self.sink.first),
            tags.sink.last.eq(sr[-1][1] if sr else self.sink.last),
            adv.eq(self.source.ready | ~self.source.valid),
            xfer_out.eq(adv & self.fir_re.source.valid & self.fir_im.source.valid),
            self.fir_re.source.ready.eq(xfer_out), self.fir_im.source.ready.eq(xfer_out),
            tags.source.ready.eq(xfer_out),
        ]
        self.sync += If(xfer_in,
            *([sr[0].eq(Cat(self.sink.first, self.sink.last))] if sr else []),
            *[sr[k].eq(sr[k - 1]) for k in range(1, len(sr))],
        )

        # Recombination y = (re.i - im.q) + j (re.q + im.i), saturated.
        # --------------------------------------------------------------
        yi = Signal((data_width + 1, True))
        yq = Signal((data_width + 1, True))
        self.comb += [
            yi.eq(self.fir_re.source.i - self.fir_im.source.q),
            yq.eq(self.fir_re.source.q + self.fir_im.source.i),
        ]
        lim = (1 << (data_width - 1)) - 1
        self.sync += [
            If(adv,
                self.source.valid.eq(self.fir_re.source.valid & self.fir_im.source.valid),
                self.source.i.eq(saturated(yi, data_width)),
                self.source.q.eq(saturated(yq, data_width)),
                self.source.first.eq(tags.source.first),
                self.source.last.eq(tags.source.last),
            ),
            If(self.clear,
                self.saturated.eq(0),
            ).Elif(xfer_out & ((yi > lim) | (yi < -lim - 1) | (yq > lim) | (yq < -lim - 1)),
                self.saturated.eq(1),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("pulse_len", size=16, offset=0,  description="Reference length (taps)."),
            CSRField("shift",     size=8,  offset=16, description="Output rescale shift."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturated", size=1, offset=0, description="Sticky: an output saturated."),
        ])
        self.comb += [
            self._config.fields.pulse_len.eq(self.pulse_len),
            self._config.fields.shift.eq(self.shift),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.saturated.eq(self.saturated),
        ]
