#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio metering: a per-channel peak/hold/clip meter and an ITU-R BS.1770 K-weighted loudness
accumulator. Both are zero-latency passthrough taps on a channel-tagged TDM stream; the host reads
the measurements through CSRs (dB conversions in :mod:`litedsp.software.drivers`)."""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess, EventSourcePulse
from litex.soc.interconnect                  import stream

from litedsp.common        import check, tdm_layout, tdm_channel
from litedsp.level.logdb   import LiteDSPLog2
from litedsp.audio.eq      import LiteDSPAudioEQ
from litedsp.audio.design  import k_weighting_sos
from litedsp.filter.design import biquad_sos_quantize

# Peak Meter ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPeakMeter(LiteXModule):
    """Per-channel peak / hold / clip meter on a TDM stream (zero-latency passthrough tap).

    Per accepted beat of channel ``c`` with magnitude ``m = |x|``: ``peak[c] = max(m, peak[c] -
    max(peak[c] >> decay_shift, 1))`` (exponential fall-back, ``2**decay_shift`` beats per
    e-fold, exact convergence to 0), ``hold[c] = max(hold[c], m)`` until ``clear``, and ``m >=
    clip_threshold`` increments the saturating 16-bit ``clip_count[c]`` and sets the sticky
    ``clip`` bit (IRQ ``ev.clip`` on the first clip). A shared :class:`LiteDSPLog2` (LUT) scans
    the peaks round-robin into ``peak_log2[c]`` (unsigned Q(int).8 ``log2(peak)``; the host
    converts with ``dBFS = 6.02*(L - (data_width - 1))``).

    Parameters
    ----------
    decay_shift : int
        Reset value of the runtime fall-back rate (1..15): ``2**decay_shift`` beats per e-fold.
    clip_threshold : int or None
        Magnitude counted as a clip (default full scale ``2**(data_width - 1) - 1``).
    """
    def __init__(self, data_width=24, n_channels=2, decay_shift=12, clip_threshold=None,
        with_csr=True, with_irq=False):
        check(data_width >= 8, "expected data_width >= 8")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(1 <= decay_shift <= 15, "expected 1 <= decay_shift <= 15")
        if clip_threshold is None:
            clip_threshold = (1 << (data_width - 1)) - 1
        check(1 <= clip_threshold <= (1 << (data_width - 1)), "expected 1 <= clip_threshold <= 2**(data_width - 1)")
        self.data_width  = data_width
        self.n_channels  = n_channels
        self.latency     = 0
        self.sink   = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.decay_shift    = Signal(4, reset=decay_shift)
        self.clip_threshold = Signal(data_width, reset=clip_threshold)
        self.clear          = Signal()
        self.peak       = [Signal(data_width, name=f"peak{c}") for c in range(n_channels)]
        self.hold       = [Signal(data_width, name=f"hold{c}") for c in range(n_channels)]
        self.clip_count = [Signal(16, name=f"clip_count{c}") for c in range(n_channels)]
        self.clip       = Signal(n_channels)
        self.log2       = LiteDSPLog2(in_width=data_width, frac_bits=8, lut=True, with_csr=False)
        self.peak_log2  = [Signal(self.log2.out_width, name=f"peak_log2{c}") for c in range(n_channels)]

        # # #

        # Passthrough tap (measurement only, zero added latency).
        # -------------------------------------------------------
        self.comb += self.sink.connect(self.source)
        xfer = Signal()
        ch   = tdm_channel(self.sink)
        x    = self.sink.data
        mag  = Signal(data_width)                                          # |x| (full scale fits).
        self.comb += [
            xfer.eq(self.sink.valid & self.sink.ready),
            mag.eq(Mux(x[-1], -x, x)),
        ]

        # Per-channel peak / hold / clip state.
        # -------------------------------------
        for c in range(n_channels):
            fall = Signal(data_width)                                      # max(peak >> shift, 1).
            dec  = Signal(data_width)                                      # Decayed peak (>= 0).
            self.comb += [
                fall.eq(Mux((self.peak[c] >> self.decay_shift) == 0, 1, self.peak[c] >> self.decay_shift)),
                dec.eq(Mux(self.peak[c] > fall, self.peak[c] - fall, 0)),
            ]
            self.sync += [
                If(self.clear,
                    self.peak[c].eq(0), self.hold[c].eq(0), self.clip_count[c].eq(0), self.clip[c].eq(0),
                ).Elif(xfer & (ch == c),
                    self.peak[c].eq(Mux(mag > dec, mag, dec)),
                    If(mag > self.hold[c], self.hold[c].eq(mag)),
                    If(mag >= self.clip_threshold,
                        self.clip[c].eq(1),
                        If(self.clip_count[c] != 0xffff, self.clip_count[c].eq(self.clip_count[c] + 1)),
                    ),
                ),
            ]

        # Round-robin log2 of the peaks (one shared LUT log2, always flowing).
        # --------------------------------------------------------------------
        idx  = Signal(max=max(2, n_channels))
        tags = [Signal(max=max(2, n_channels), name=f"tag{k}") for k in range(self.log2.latency)]
        self.comb += [
            self.log2.sink.valid.eq(1),
            self.log2.sink.data.eq(Array(self.peak)[idx]),
            self.log2.source.ready.eq(1),
        ]
        self.sync += If(self.log2.sink.ready,
            idx.eq(Mux(idx == n_channels - 1, 0, idx + 1)),
            tags[0].eq(idx),
            *[tags[k].eq(tags[k - 1]) for k in range(1, len(tags))],
        )
        for c in range(n_channels):
            self.sync += If(self.log2.source.valid & (tags[-1] == c), self.peak_log2[c].eq(self.log2.source.data))

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev      = EventManager()
        self.ev.clip = EventSourceProcess(edge="rising", description="A channel clipped (sticky flag set).")
        self.ev.finalize()
        self.comb += self.ev.clip.trigger.eq(self.clip != 0)

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear peaks, holds, clip counts and flags."),
        ])
        self._decay_shift = CSRStorage(4, reset=self.decay_shift.reset.value, name="decay_shift",
            description="Peak fall-back rate: 2**decay_shift beats per e-fold.")
        self._clip_threshold = CSRStorage(self.data_width, reset=self.clip_threshold.reset.value,
            name="clip_threshold", description="Magnitude counted as a clip.")
        self._clip = CSRStatus(self.n_channels, name="clip", description="Sticky per-channel clip flags.")
        self.comb += [
            self.clear.eq(self._control.fields.clear),
            self.decay_shift.eq(self._decay_shift.storage),
            self.clip_threshold.eq(self._clip_threshold.storage),
            self._clip.status.eq(self.clip),
        ]
        for c in range(self.n_channels):
            for name, sig, desc in (
                ("peak",       self.peak[c],       "decaying peak magnitude"),
                ("hold",       self.hold[c],       "peak magnitude since clear"),
                ("clip_count", self.clip_count[c], "clips since clear (saturating)"),
                ("peak_log2",  self.peak_log2[c],  "log2(peak), unsigned Q(int).8"),
            ):
                csr = CSRStatus(len(sig), name=f"{name}{c}", description=f"Channel {c} {desc}.")
                setattr(self, f"_{name}{c}", csr)
                self.comb += csr.status.eq(sig)

# Loudness -----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLoudness(LiteXModule):
    """ITU-R BS.1770 loudness front-end: K-weighting + per-hop weighted sum of squares (zero-latency
    passthrough tap).

    The stream is tapped into a side :class:`LiteDSPAudioEQ` (2 bands: the BS.1770 high shelf and
    RLB high-pass designed for ``sample_rate``); every K-weighted beat is squared, weighted by its
    channel's ``channel_weights`` entry (Q2.14; BS.1770 uses 1.0 for L/R/C and 1.41 for the
    surrounds, 0 for the LFE) and accumulated. After ``hop_samples`` frames the accumulator is
    latched into ``sum_sq`` (``hop_count`` increments, ``update`` strobes, IRQ ``ev.update``) and
    restarted; the host builds the 400 ms momentary / 3 s short-term / gated integrated
    loudness from the hop sums (:class:`litedsp.software.drivers.LoudnessDriver`):
    ``LKFS = -0.691 + 10*log10(sum_sq / (hop_samples * 2**(2*(data_width - 1))))``.

    The side engine needs ``cycles_per_sample`` (18) clock cycles per beat; a beat arriving
    while it is busy is dropped and sets the sticky ``overrun`` flag.
    """
    def __init__(self, data_width=24, n_channels=2, sample_rate=48000, hop_samples=4800,
        channel_weights=None, coeff_width=32, frac_bits=28, with_csr=True, with_irq=False):
        check(data_width >= 8, "expected data_width >= 8")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(sample_rate > 0, "expected sample_rate > 0")
        check(1 <= hop_samples <= 1 << 20, "expected 1 <= hop_samples <= 2**20")
        if channel_weights is None:
            channel_weights = [1.0]*n_channels
        check(len(channel_weights) == n_channels, "expected one channel weight per channel")
        check(all(0.0 <= w < 4.0 for w in channel_weights), "expected channel weights in [0, 4)")
        sections, _ = biquad_sos_quantize(k_weighting_sos(sample_rate), coeff_width, frac_bits)
        self.data_width      = data_width
        self.n_channels      = n_channels
        self.sample_rate     = sample_rate
        self.hop_samples     = hop_samples
        self.channel_weights = [int(round(w*(1 << 14))) for w in channel_weights]
        self.sections        = sections
        self.latency         = 0
        self.sink   = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.eq = LiteDSPAudioEQ(data_width=data_width, n_bands=2, n_channels=n_channels,
            coeff_width=coeff_width, frac_bits=frac_bits, sections=sections, with_csr=False)
        self.cycles_per_sample = self.eq.cycles_per_sample
        hop_beats = hop_samples*n_channels
        acc_width = 2*data_width - 1 + 2 + max(1, int(math.ceil(math.log2(hop_beats))))
        self.clear     = Signal()
        self.sum_sq    = Signal(acc_width)
        self.hop_count = Signal(32)
        self.update    = Signal()
        self.overrun   = Signal()

        # # #

        # Passthrough tap feeding the side K-weighting engine.
        # ----------------------------------------------------
        self.comb += self.sink.connect(self.source)
        xfer = Signal()
        self.comb += [
            xfer.eq(self.sink.valid & self.sink.ready),
            self.eq.sink.valid.eq(xfer),
            self.eq.sink.data.eq(self.sink.data),
            self.eq.source.ready.eq(1),
        ]
        if n_channels > 1:
            self.comb += self.eq.sink.channel.eq(self.sink.channel)
        self.sync += If(self.clear, self.overrun.eq(0)).Elif(xfer & ~self.eq.sink.ready, self.overrun.eq(1))

        # Square, weight, accumulate per hop.
        # -----------------------------------
        y   = self.eq.source.data
        ch  = tdm_channel(self.eq.source)
        v1, v2  = Signal(), Signal()
        ch1     = Signal(max=max(2, n_channels))
        sq      = Signal(2*data_width - 1)                                 # y*y (unsigned).
        wsq     = Signal(2*data_width - 1 + 16)                            # sq * weight (Q2.14).
        term    = Signal(acc_width)
        acc     = Signal(acc_width)
        count   = Signal(max=hop_beats + 1)
        weights = Array(Constant(w, 16) for w in self.channel_weights)
        self.sync += [
            v1.eq(self.eq.source.valid), sq.eq(y*y), ch1.eq(ch),
            v2.eq(v1), wsq.eq(sq*weights[ch1]),
        ]
        self.comb += term.eq(wsq >> 14)
        self.sync += [
            self.update.eq(0),
            If(self.clear,
                acc.eq(0), count.eq(0), self.hop_count.eq(0),
            ).Elif(v2,
                If(count == hop_beats - 1,
                    self.sum_sq.eq(acc + term), acc.eq(0), count.eq(0),
                    self.hop_count.eq(self.hop_count + 1), self.update.eq(1),
                ).Else(
                    acc.eq(acc + term), count.eq(count + 1),
                ),
            ),
        ]

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev        = EventManager()
        self.ev.update = EventSourcePulse(description="A hop sum was latched.")
        self.ev.finalize()
        self.comb += self.ev.update.trigger.eq(self.update)

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Restart the hop, clear hop_count and overrun."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("overrun", size=1, offset=0, description="Sticky: a beat was dropped by the busy K-weighting engine."),
        ])
        self._sum_sq    = CSRStatus(len(self.sum_sq), name="sum_sq", description="Weighted K-weighted sum of squares of the last hop.")
        self._hop_count = CSRStatus(32, name="hop_count", description="Hops latched since clear.")
        self._config = CSRStatus(fields=[
            CSRField("n_channels",  size=4,  offset=0,  description="Channels."),
            CSRField("data_width",  size=6,  offset=4,  description="Sample width."),
            CSRField("hop_samples", size=21, offset=10, description="Frames per hop."),
        ])
        self.comb += [
            self.clear.eq(self._control.fields.clear),
            self._status.fields.overrun.eq(self.overrun),
            self._sum_sq.status.eq(self.sum_sq),
            self._hop_count.status.eq(self.hop_count),
            self._config.fields.n_channels.eq(self.n_channels),
            self._config.fields.data_width.eq(self.data_width),
            self._config.fields.hop_samples.eq(self.hop_samples),
        ]
