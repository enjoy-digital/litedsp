#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Array processing: narrowband phase-shift beamforming, phase-comparison monopulse."""

from functools import reduce
from operator  import add, and_

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, scaled, bits_for

# Beamformer ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBeamformer(LiteXModule):
    """Narrowband phase-shift beamformer: ``n_elements`` I/Q streams to ``n_beams`` beams.

    The element streams are joined (all must present a sample) and each beam is
    ``y[k] = sum_e w[k][e] * x[e]`` with complex weights in signed Q(2).weight_frac (four real
    products per element, an adder tree, then ``scaled(sum, shift, data_width)`` with the
    sticky ``saturated`` flag; ``shift`` defaults to ``weight_frac`` so unity weights pass the
    element scale). Beams are computed serially, one per cycle (``cycles_per_sample =
    n_beams``); with more than one beam the output carries a ``channel`` tag. Weights live in
    active / shadow registers: write ``weight_index`` (``beam * n_elements + element``),
    ``weight_re`` / ``weight_im`` with ``weight_we``, then ``commit`` copies the shadow set
    between samples (atomic per sample). Reset weights are the broadside average
    (``1 / n_elements``). Latency 3 for a single beam. See
    ``litedsp.radar.design.steering_weights`` for the host-side steering / taper maths.
    """
    def __init__(self, n_elements=4, n_beams=1, data_width=16, weight_width=16, weight_frac=14,
        shift=None, with_csr=True):
        check(1 <= n_elements <= 16 and 1 <= n_beams <= 8,
              "expected 1 <= n_elements <= 16, 1 <= n_beams <= 8")
        check(weight_frac < weight_width, "expected weight_frac < weight_width")
        if shift is None:
            shift = weight_frac
        check(0 <= shift <= weight_frac + bits_for(n_elements) + 1,
              "expected a shift within the accumulator range")
        self.n_elements   = n_elements
        self.n_beams      = n_beams
        self.data_width   = data_width
        self.weight_width = weight_width
        self.weight_frac  = weight_frac
        self.shift        = shift
        self.cycles_per_sample = n_beams
        self.latency      = 3 if n_beams == 1 else None
        layout = iq_layout(data_width) + ([("channel", bits_for(n_beams - 1))] if n_beams > 1
                                                                else [])
        self.sinks  = [stream.Endpoint(iq_layout(data_width)) for _ in range(n_elements)]
        self.source = stream.Endpoint(layout)
        self.weight_index = Signal(max=n_beams*n_elements)
        self.weight_re    = Signal((weight_width, True))
        self.weight_im    = Signal((weight_width, True))
        self.weight_we    = Signal()
        self.commit       = Signal()
        self.commit_pending = Signal()
        self.saturated    = Signal()                                    # Sticky.
        self.clear        = Signal()

        # # #

        N, K, WW, WF = n_elements, n_beams, weight_width, weight_frac
        w0 = int(round((1 << WF)/N))
        # Active and shadow weight sets.
        act_re = [[Signal((WW, True), reset=w0, name=f"w_re{k}_{e}") for e in range(N)]
            for k in range(K)]
        act_im = [[Signal((WW, True), name=f"w_im{k}_{e}") for e in range(N)] for k in range(K)]
        sh_re  = [[Signal((WW, True), reset=w0, name=f"s_re{k}_{e}") for e in range(N)]
            for k in range(K)]
        sh_im  = [[Signal((WW, True), name=f"s_im{k}_{e}") for e in range(N)] for k in range(K)]
        self.sync += [
            If(self.weight_we,
                *[If(self.weight_index == k*N + e, sh_re[k][e].eq(self.weight_re),
                     sh_im[k][e].eq(self.weight_im))
                  for k in range(K) for e in range(N)],
            ),
        ]

        # Join and beam sequencing.
        # -------------------------
        adv, all_valid, capture = Signal(), Signal(), Signal()
        beam = Signal(max=max(K, 2))
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            all_valid.eq(reduce(and_, [s.valid for s in self.sinks])),
            capture.eq(adv & (beam == 0) & all_valid),
        ]
        for e, s in enumerate(self.sinks):                              # Join: ready depends on the
            # *other* sinks' valid only.
            others = [o.valid for k, o in enumerate(self.sinks) if k != e]
            self.comb += s.ready.eq(adv & (beam == 0) & (reduce(and_, others) if others else 1))
        # Stage 1: the captured sample (held during the beam loop).
        xi = [Signal((data_width, True), name=f"xi{e}") for e in range(N)]
        xq = [Signal((data_width, True), name=f"xq{e}") for e in range(N)]
        v1, b1 = Signal(), Signal(max=max(K, 2))
        self.sync += If(adv,
            If(capture, *[xi[e].eq(self.sinks[e].i) for e in range(N)],
               *[xq[e].eq(self.sinks[e].q) for e in range(N)]),
            v1.eq(capture | (beam != 0)),
            b1.eq(beam),
            If((beam != 0) | capture,
                If(beam == K - 1, beam.eq(0)).Else(beam.eq(beam + 1)),
            ),
            # Weight commit at a sample boundary (beam 0 of the next sample; the previous sample's
            # last beam registers its products with the old set at this same edge).
            If(self.commit_pending & (beam == 0),
                *[act_re[k][e].eq(sh_re[k][e]) for k in range(K) for e in range(N)],
                *[act_im[k][e].eq(sh_im[k][e]) for k in range(K) for e in range(N)],
                self.commit_pending.eq(0),
            ),
        )
        self.sync += If(self.commit, self.commit_pending.eq(1))         # Not gated by adv: a pulse.
        # Stage 2: products for beam b1.
        PW = data_width + WW
        pi = [Signal((PW, True), name=f"pi{e}") for e in range(N)]     # wr*xi - wi*xq
        pq = [Signal((PW, True), name=f"pq{e}") for e in range(N)]     # wr*xq + wi*xi
        wr_sel = [Array([act_re[k][e] for k in range(K)])[b1] for e in range(N)]
        wi_sel = [Array([act_im[k][e] for k in range(K)])[b1] for e in range(N)]
        m = {}
        for e in range(N):
            for n, (a, b) in (("rr", (wr_sel[e], xi[e])), ("iq", (wi_sel[e], xq[e])),
                              ("rq", (wr_sel[e], xq[e])), ("ir", (wi_sel[e], xi[e]))):
                m[n, e] = Signal((PW, True), name=f"m_{n}{e}")
                self.comb += m[n, e].eq(a*b)
        v2, b2 = Signal(), Signal(max=max(K, 2))
        self.sync += If(adv,
            *[pi[e].eq(m["rr", e] - m["iq", e]) for e in range(N)],
            *[pq[e].eq(m["rq", e] + m["ir", e]) for e in range(N)],
            v2.eq(v1), b2.eq(b1),
        )
        # Stage 3: sums, scaling, output.
        AW = PW + bits_for(N)
        si, sq = Signal((AW, True)), Signal((AW, True))
        self.comb += [si.eq(reduce(add, pi)), sq.eq(reduce(add, pq))]
        yi, ovi = scaled(si, shift, data_width)
        yq, ovq = scaled(sq, shift, data_width)
        self.sync += [
            If(adv,
                self.source.valid.eq(v2),
                self.source.i.eq(yi), self.source.q.eq(yq),
                *([self.source.channel.eq(b2)] if K > 1 else []),
            ),
            If(self.clear, self.saturated.eq(0)).Elif(adv & v2 & (ovi | ovq), self.saturated.eq(1)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        WW = self.weight_width
        self._weight_index = CSRStorage(len(self.weight_index), name="weight_index",
                                        description="Shadow weight index (beam * n_elements + "
                                                    "element).")
        self._weight = CSRStorage(fields=[
            CSRField("re", size=WW, offset=0,  description=f"Weight real part (signed Q2.{self.weight_frac})."),
            CSRField("im", size=WW, offset=16, description="Weight imaginary part."),
        ], description="Writing loads the shadow weight at weight_index.")
        self._control = CSRStorage(fields=[
            CSRField("commit", size=1, offset=0, pulse=True, description="Copy the shadow weights between samples."),
            CSRField("clear",  size=1, offset=1, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("commit_pending", size=1, offset=0, description="A commit waits for the sample boundary."),
            CSRField("saturated",      size=1, offset=1, description="Sticky: a beam output saturated."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_elements",  size=5, offset=0, description="Array elements."),
            CSRField("n_beams",     size=4, offset=8, description="Beams per sample."),
            CSRField("weight_frac", size=5, offset=16, description="Weight fractional bits."),
        ])
        self.comb += [
            self.weight_index.eq(self._weight_index.storage),
            self.weight_re.eq(self._weight.fields.re), self.weight_im.eq(self._weight.fields.im),
            self.weight_we.eq(self._weight.re),
            self.commit.eq(self._control.fields.commit), self.clear.eq(self._control.fields.clear),
            self._status.fields.commit_pending.eq(self.commit_pending),
            self._status.fields.saturated.eq(self.saturated),
            self._config.fields.n_elements.eq(self.n_elements),
            self._config.fields.n_beams.eq(self.n_beams),
            self._config.fields.weight_frac.eq(self.weight_frac),
        ]

# Monopulse ----------------------------------------------------------------------------------------

from litedsp.common             import angle_layout
from litedsp.mixing.mixer       import LiteDSPMixer
from litedsp.generation.cordic  import LiteDSPCORDIC

@ResetInserter()
class LiteDSPMonopulse(LiteXModule):
    """Phase-comparison monopulse: the phase of ``a * conj(b)`` for two element / sub-array
    streams.

    ``sink_a`` and ``sink_b`` (I/Q, joined) feed a :class:`LiteDSPMixer` in down-conversion mode
    (``a * conj(b)``, rounded to ``data_width``) and a vectoring :class:`LiteDSPCORDIC` gives the
    angle on :func:`~litedsp.common.angle_layout` (full circle = ``2**angle_width``); the
    ``first`` / ``last`` tags of ``sink_a`` are carried through a FIFO join. The angle of arrival
    follows from the phase, the element spacing and the wavelength on the host. Latency
    ``2 + cordic.latency``.
    """
    def __init__(self, data_width=16, angle_width=16, stages=None, with_csr=True):
        self.data_width  = data_width
        self.angle_width = angle_width
        self.sink_a = stream.Endpoint(iq_layout(data_width))
        self.sink_b = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(angle_layout(angle_width))

        # # #

        self.mixer  = LiteDSPMixer(data_width=data_width, with_csr=False)
        self.cordic = LiteDSPCORDIC(data_width=data_width, angle_width=angle_width, stages=stages,
            mode="vectoring", with_csr=False)
        self.latency = self.mixer.latency + self.cordic.latency
        self.tags = stream.SyncFIFO([("pad", 1)], self.latency + 4)
        self.comb += [
            self.mixer.mode.eq(0),                                      # Down: a * conj(b).
            self.sink_a.connect(self.mixer.sink_a, omit={"first", "last"}),
            self.sink_b.connect(self.mixer.sink_b, omit={"first", "last"}),
            self.mixer.source.connect(self.cordic.sink, omit={"i", "q", "first", "last"}),
            self.cordic.sink.x.eq(self.mixer.source.i),
            self.cordic.sink.y.eq(self.mixer.source.q),
            # Tags: pushed with the joined input beat, popped with the output beat.
            self.tags.sink.valid.eq(self.sink_a.valid & self.sink_a.ready),
            self.tags.sink.first.eq(self.sink_a.first),
            self.tags.sink.last.eq(self.sink_a.last),
            self.cordic.source.connect(self.source, omit={"mag", "first", "last"}),
            self.source.first.eq(self.tags.source.first),
            self.source.last.eq(self.tags.source.last),
            self.tags.source.ready.eq(self.source.valid & self.source.ready),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("angle_width", size=6, offset=0, description="Angle word width (full circle = 2^angle_width)."),
            CSRField("latency",     size=8, offset=8, description="Pipeline latency in cycles."),
        ])
        self.comb += [
            self._config.fields.angle_width.eq(self.angle_width),
            self._config.fields.latency.eq(self.latency),
        ]
