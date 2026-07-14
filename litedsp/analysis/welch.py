#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import check, iq_layout, real_layout
from litedsp.analysis.window import LiteDSPWindow
from litedsp.analysis.fft    import LiteDSPFFT
from litedsp.analysis.psd    import LiteDSPPSD

# Welch PSD ----------------------------------------------------------------------------------------

class LiteDSPWelchPSD(LiteXModule):
    """Windowed, averaged power spectral density: Window -> FFT -> PSD, with segment overlap.

    Applies a window before the FFT (reducing spectral leakage vs a bare PSD) and averages
    ``2**avg_log2`` segments. Output is the averaged spectrum in natural bin order. With
    ``overlap`` > 0, successive ``N``-sample segments share ``N*overlap/100`` samples (the
    Welch method proper): the shared tail of each segment is replayed from an internal history
    RAM into the Window -> FFT -> PSD chain, recovering the variance lost to window tapering
    for a given input length.

    The replay runs at fabric clock while the input stalls, so the sustained input rate is
    bounded by roughly ``f_clk * (1 - overlap/100)`` (each ``N``-sample segment is followed by
    ``N*overlap/100`` replay cycles; PSD readout stalls add on top). ``overlap=0`` (the
    default) keeps the chain fully streaming and is bit-compatible with the non-overlapped
    implementation.

    Parameters
    ----------
    avg_log2 : int
        Windowed FFT segments averaged per emitted spectrum, as a power of two
        (``2**avg_log2``); more averaging lowers the variance of the estimate but lengthens
        the update interval.
    overlap : int
        Segment overlap in percent (0, 25, 50 or 75); successive segments share
        ``N*overlap/100`` samples, which must be an integer. Higher overlap yields more
        segments (lower variance) from the same input length, at the cost of input
        throughput (see above).
    """
    def __init__(self, N=256, data_width=16, avg_log2=2, window="hann", overlap=0, with_csr=True):
        check(N >= 2 and (N & (N - 1)) == 0, "N must be a power of two >= 2.")
        check(overlap in (0, 25, 50, 75), "overlap must be 0, 25, 50 or 75 (percent).")
        check((N*overlap) % 100 == 0, "N*overlap/100 must be an integer number of samples.")
        self.N       = N
        self.overlap = overlap
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.latency = None  # Variable (frame-accumulating composite).

        # # #

        self.window = LiteDSPWindow(N, data_width=data_width, window=window, with_csr=False)
        self.fft    = LiteDSPFFT(N, data_width=data_width, with_csr=False)
        self.psd    = LiteDSPPSD(N, fft_latency=self.fft.latency, data_width=data_width,
            avg_log2=avg_log2, with_csr=with_csr)
        self.source = self.psd.source
        self.comb += [
            self.window.source.connect(self.fft.sink),
            self.fft.source.connect(self.psd.sink),
        ]

        # Segmentation: straight passthrough without overlap; with overlap, feed and record
        # each segment, then replay its tail from a history RAM as the next segment's head.
        # ----------------------------------------------------------------------------------
        if overlap == 0:
            self.comb += self.sink.connect(self.window.sink)
        else:
            V = (N*overlap)//100  # Samples shared between successive segments.
            S = N - V             # Segment step (new samples per segment).

            # History RAM: the current segment's samples ({q, i} packed), async read + sync
            # write. During replay, position S+k is read (previous tail) and rewritten at
            # position k (new head) — reads always precede overwrites since S > 0.
            hist_mem = Memory(2*data_width, N)
            hist_wp  = hist_mem.get_port(write_capable=True)
            hist_rp  = hist_mem.get_port(async_read=True)
            self.specials += hist_mem, hist_wp, hist_rp

            pos    = Signal(max=N)          # Write position within the current segment.
            replay = Signal(max=max(2, V))  # Replayed-sample index (0..V-1).

            self.fsm = fsm = FSM(reset_state="FEED")
            fsm.act("FEED",
                self.sink.connect(self.window.sink),
                hist_wp.adr.eq(pos),
                hist_wp.dat_w.eq(Cat(self.sink.i, self.sink.q)),
                hist_wp.we.eq(self.sink.valid & self.window.sink.ready),
                If(self.sink.valid & self.window.sink.ready,
                    If(pos == (N - 1),
                        NextState("REPLAY"),
                    ).Else(
                        NextValue(pos, pos + 1),
                    )
                )
            )
            fsm.act("REPLAY",
                # Input stalls (sink.ready = 0) while the previous segment's last V samples
                # are replayed into the chain as the new segment's first V samples.
                self.window.sink.valid.eq(1),
                self.window.sink.i.eq(hist_rp.dat_r[:data_width]),
                self.window.sink.q.eq(hist_rp.dat_r[data_width:]),
                hist_rp.adr.eq(S + replay),
                hist_wp.adr.eq(replay),
                hist_wp.dat_w.eq(hist_rp.dat_r),
                hist_wp.we.eq(self.window.sink.ready),
                If(self.window.sink.ready,
                    If(replay == (V - 1),
                        NextValue(replay, 0),
                        NextValue(pos, V),
                        NextState("FEED"),
                    ).Else(
                        NextValue(replay, replay + 1),
                    )
                )
            )
