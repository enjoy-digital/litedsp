#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common            import check, angle_layout, iq_layout, real_layout
from litedsp.generation.nco    import LiteDSPNCO
from litedsp.generation.cordic import LiteDSPCORDIC
from litedsp.motor.observer    import LiteDSPAngleTracker

# Resolver-to-Digital Converter --------------------------------------------------------------------

@ResetInserter()
class LiteDSPResolverDigital(LiteXModule):
    """Resolver-to-digital converter: excitation output, synchronous demodulation, tracking loop.

    The excitation sine (``source_exc``, one sample per accepted input, period ``decimation``
    samples -- ``f_exc = f_s/decimation``) drives the resolver primary; the ADCs sample the sine
    and cosine windings (``sink``: i = sine, q = cosine) at the same rate. Each winding is
    multiplied by the reference delayed by ``phase_offset`` samples (analog loop delay) and
    integrated exactly over one excitation period (a boxcar of ``decimation`` samples cancels
    the carrier ripple), the two sums are vectored by a CORDIC (``atan2(sin_sum, cos_sum)``)
    and the resulting raw angle, one per period (rate ``1/decimation``), is smoothed by an
    internal :class:`LiteDSPAngleTracker` (``source``, ``speed``). Setting ``phase_offset`` is
    the only calibration: a wrong offset lowers the demodulated amplitude (``raw_mag``
    status) without biasing the angle.

    Parameters
    ----------
    angle_width : int
        Output angle width (full turn = 2**angle_width).
    decimation : int
        Excitation period in input samples (>= 4, ROM depth).
    kp_shift, ki_shift : int
        Tracking-loop reset gains (see :class:`LiteDSPAngleTracker`).
    frac_bits : int
        Tracking-loop fractional bits.
    stages : int
        CORDIC iterations (defaults to ``angle_width``).
    """
    def __init__(self, data_width=16, angle_width=16, decimation=32, kp_shift=3, ki_shift=8,
        frac_bits=14, stages=None, with_csr=True):
        check(data_width >= 4, "expected data_width >= 4")
        check(decimation >= 4, "expected decimation >= 4")
        if stages is None:
            stages = angle_width
        self.data_width  = data_width
        self.angle_width = angle_width
        self.decimation  = decimation
        D  = decimation
        AW = 2*data_width + int(math.ceil(math.log2(D)))               # Exact boxcar sum.
        self.sink       = stream.Endpoint(iq_layout(data_width))       # Sine / cosine windings.
        self.source_exc = stream.Endpoint(real_layout(data_width))     # Excitation sample.
        self.source     = stream.Endpoint(angle_layout(angle_width))   # Tracked angle.
        self.phase_offset = Signal(max=D)                              # Demodulation delay.
        self.raw_angle    = Signal((angle_width, True))                # Last demodulated angle.
        self.raw_mag      = Signal((AW, True))                         # Demodulated amplitude.

        # # #

        # Submodules.
        # -----------
        self.cordic  = cordic = LiteDSPCORDIC(data_width=AW - 1, angle_width=angle_width,
            stages=stages, mode="vectoring", with_csr=False)
        self.tracker = tracker = LiteDSPAngleTracker(angle_width=angle_width, frac_bits=frac_bits,
            kp_shift=kp_shift, ki_shift=ki_shift, with_csr=False)
        self.speed   = tracker.speed
        self.kp_shift, self.ki_shift = tracker.kp_shift, tracker.ki_shift
        self.latency = 1 + cordic.latency + tracker.latency

        # Excitation ROM (two asynchronous read ports: DAC phase and delayed demodulation phase).
        # -------------------------------------------------------------------------------------
        rom  = Memory(data_width, D, init=LiteDSPNCO.build_lut(D, data_width, math.sin))
        dacp = rom.get_port(async_read=True)
        demp = rom.get_port(async_read=True)
        self.specials += rom, dacp, demp
        phase   = Signal(max=D)
        dem_ph  = Signal(max=2*D)
        self.comb += [
            dacp.adr.eq(phase),
            dem_ph.eq(phase + self.phase_offset),
            demp.adr.eq(Mux(dem_ph >= D, dem_ph - D, dem_ph)),
        ]

        # Handshake: an input sample is consumed when the DAC sample can be emitted and the
        # accumulator window may complete (CORDIC ready).
        # -----------------------------------------------------------------------------------
        adv    = Signal()
        xfer   = Signal()
        is_end = Signal()
        self.comb += [
            is_end.eq(phase == D - 1),
            adv.eq((self.source_exc.ready | ~self.source_exc.valid) & (~is_end | cordic.sink.ready)),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]
        self.sync += [
            If(xfer, If(is_end, phase.eq(0)).Else(phase.eq(phase + 1))),
            If(self.source_exc.ready | ~self.source_exc.valid,
                self.source_exc.data.eq(dacp.dat_r),
                self.source_exc.valid.eq(self.sink.valid & (~is_end | cordic.sink.ready)),
            ),
        ]

        # Synchronous demodulation: exact boxcar over one period.
        # -------------------------------------------------------
        reference = Signal((data_width, True))        # Delayed excitation sample.
        p_sin   = Signal((2*data_width, True))
        p_cos   = Signal((2*data_width, True))
        acc_sin = Signal((AW, True))
        acc_cos = Signal((AW, True))
        sum_sin = Signal((AW, True))
        sum_cos = Signal((AW, True))
        self.comb += [
            reference.eq(demp.dat_r),
            p_sin.eq(self.sink.i*reference),
            p_cos.eq(self.sink.q*reference),
            sum_sin.eq(acc_sin + p_sin),
            sum_cos.eq(acc_cos + p_cos),
        ]
        self.sync += If(xfer,
            If(is_end,
                acc_sin.eq(0),
                acc_cos.eq(0),
            ).Else(
                acc_sin.eq(sum_sin),
                acc_cos.eq(sum_cos),
            ),
        )
        self.comb += [
            cordic.sink.valid.eq(xfer & is_end),
            cordic.sink.x.eq(sum_cos),
            cordic.sink.y.eq(sum_sin),
        ]

        # Tracking loop on the raw angle.
        # -------------------------------
        self.comb += [
            cordic.source.connect(tracker.sink, omit={"mag", "angle"}),
            tracker.sink.angle.eq(cordic.source.angle),
            tracker.source.connect(self.source),
        ]
        self.sync += If(cordic.source.valid & cordic.source.ready,
            self.raw_angle.eq(cordic.source.angle),
            self.raw_mag.eq(cordic.source.mag),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._phase_offset = CSRStorage(len(self.phase_offset), name="phase_offset",
            description="Demodulation phase delay in samples (analog loop delay calibration).")
        self._gains = CSRStorage(fields=[
            CSRField("kp_shift", size=5, offset=0, reset=self.kp_shift.reset.value,
                description="Tracking-loop proportional shift."),
            CSRField("ki_shift", size=5, offset=8, reset=self.ki_shift.reset.value,
                description="Tracking-loop integral shift."),
        ])
        self._speed     = CSRStatus(len(self.speed), name="speed",
            description="Tracked speed (angle units per excitation period, Q.frac_bits).")
        self._raw_angle = CSRStatus(self.angle_width, name="raw_angle", description="Last demodulated angle.")
        self._raw_mag   = CSRStatus(len(self.raw_mag), name="raw_mag",
            description="Demodulated amplitude (maximize with phase_offset).")
        self.comb += [
            self.phase_offset.eq(self._phase_offset.storage),
            self.kp_shift.eq(self._gains.fields.kp_shift),
            self.ki_shift.eq(self._gains.fields.ki_shift),
            self._speed.status.eq(self.speed),
            self._raw_angle.status.eq(self.raw_angle),
            self._raw_mag.status.eq(self.raw_mag),
        ]
