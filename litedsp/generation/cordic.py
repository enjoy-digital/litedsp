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

from litedsp.common import check, scaled

# Angle convention: signed, full circle = 2**angle_width (so pi = 2**(angle_width-1)).

# Helpers ------------------------------------------------------------------------------------------

def cordic_gain(stages):
    """CORDIC processing gain K = prod sqrt(1 + 2**-2i)."""
    k = 1.0
    for i in range(stages):
        k *= math.sqrt(1 + 2.0**(-2*i))
    return k

# CORDIC -------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCORDIC(LiteXModule):
    """Pipelined CORDIC (one iteration per stage), gain-compensated, full-circle.

    ``mode="rotation"``: rotate ``(x, y)`` by ``z`` -> ``(x, y)``. With ``y=0`` and ``x`` at
    full scale this yields ``(cos z, sin z)``.
    ``mode="vectoring"``: ``(x, y)`` -> magnitude ``sqrt(x**2 + y**2)`` on ``mag`` and phase
    ``atan2(y, x)`` on ``angle``.

    Quadrant pre-rotation extends convergence to the full circle; the output is multiplied by
    1/K so magnitude/rotation are unity-gain. Pure feedforward pipeline (``latency =
    stages + 2``), so backpressure simply freezes it.

    Parameters
    ----------
    angle_width : int
        Phase word width in bits; the full circle spans 2**angle_width (pi = 2**(angle_width-1)).
        Defaults to data_width.
    stages : int
        Number of pipelined CORDIC iterations; each adds ~1 bit of result precision and one
        cycle of latency (latency = stages + 2). Defaults to data_width.
    mode : str
        "rotation" (rotate (x, y) by z, e.g. sin/cos generation) or "vectoring" (magnitude on
        ``mag`` and atan2(y, x) on ``angle``).
    """
    def __init__(self, data_width=16, angle_width=None, stages=None, mode="rotation", with_csr=True):
        check(mode in ["rotation", "vectoring"], "expected mode in ['rotation', 'vectoring']")
        if angle_width is None:
            angle_width = data_width
        if stages is None:
            stages = data_width
        self.data_width  = data_width
        self.angle_width = angle_width
        self.mode        = mode
        self.latency     = stages + 2

        W   = data_width + 2       # Datapath guard bits (gain growth ~1.65x).
        Wz  = angle_width + 2      # Angle guard bits.
        PI  = 1 << (angle_width - 1)
        if mode == "rotation":
            self.sink   = stream.Endpoint([("x", (data_width, True)), ("y", (data_width, True)),
                                           ("z", (angle_width, True))])
            self.source = stream.Endpoint([("x", (data_width, True)), ("y", (data_width, True))])
        else:
            self.sink   = stream.Endpoint([("x", (data_width, True)), ("y", (data_width, True))])
            self.source = stream.Endpoint([("mag", (data_width + 1, True)), ("angle", (angle_width, True))])

        # # #

        atan = [int(round(math.atan(2.0**(-i))/(2*math.pi)*(1 << angle_width))) for i in range(stages)]
        kinv = int(round((1/cordic_gain(stages))*((1 << 15) - 1)))  # 1/K in Q1.15.

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        x = [Signal((W,  True)) for _ in range(stages + 1)]
        y = [Signal((W,  True)) for _ in range(stages + 1)]
        z = [Signal((Wz, True)) for _ in range(stages + 1)]

        # Pre-rotation into the convergence region, registered as stage 0.
        # ----------------------------------------------------------------
        x_pre, y_pre, z_pre = Signal((W, True)), Signal((W, True)), Signal((Wz, True))
        if mode == "rotation":
            zin   = self.sink.z
            flip  = Signal()
            z_rot = Signal((angle_width, True))                    # zin + pi, wrapped mod 2pi.
            self.comb += [
                flip.eq(zin[angle_width-1] ^ zin[angle_width-2]),  # |z| > pi/2.
                z_rot.eq(zin + PI),
                x_pre.eq(Mux(flip, -self.sink.x, self.sink.x)),
                y_pre.eq(Mux(flip, -self.sink.y, self.sink.y)),
                z_pre.eq(Mux(flip, z_rot, zin)),
            ]
        else:
            xneg = self.sink.x[data_width-1]
            self.comb += [
                x_pre.eq(Mux(xneg, -self.sink.x, self.sink.x)),
                y_pre.eq(Mux(xneg, -self.sink.y, self.sink.y)),
                z_pre.eq(Mux(xneg, Mux(self.sink.y[data_width-1], -PI, PI), 0)),
            ]
        self.sync += If(adv, x[0].eq(x_pre), y[0].eq(y_pre), z[0].eq(z_pre))

        # Iterations.
        # -----------
        for i in range(stages):
            dpos = Signal()  # True -> d = +1.
            if mode == "rotation":
                self.comb += dpos.eq(~z[i][Wz-1])      # d = sign(z): drive z -> 0.
            else:
                self.comb += dpos.eq(y[i][W-1])        # d = -sign(y): drive y -> 0.
            sh_x = x[i] >> i
            sh_y = y[i] >> i
            self.sync += If(adv,
                x[i+1].eq(x[i] - Mux(dpos,  sh_y, -sh_y)),
                y[i+1].eq(y[i] + Mux(dpos,  sh_x, -sh_x)),
                z[i+1].eq(z[i] - Mux(dpos,  atan[i], -atan[i])),
            )

        # Output: gain-compensate (rotation/magnitude) and register.
        # ----------------------------------------------------------
        if mode == "rotation":
            cx, _ = scaled(x[stages]*kinv, 15, data_width)
            cy, _ = scaled(y[stages]*kinv, 15, data_width)
            self.sync += If(adv, self.source.x.eq(cx), self.source.y.eq(cy))
        else:
            cmag, _ = scaled(x[stages]*kinv, 15, data_width + 1)
            self.sync += If(adv, self.source.mag.eq(cmag), self.source.angle.eq(z[stages]))

        valid_pipe = Signal(self.latency)
        self.sync += If(adv, valid_pipe.eq(Cat(self.sink.valid, valid_pipe[:-1])))
        self.comb += self.source.valid.eq(valid_pipe[-1])

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._latency = CSRStatus(16, reset=self.latency, name="latency",
            description="CORDIC pipeline latency (cycles).")
