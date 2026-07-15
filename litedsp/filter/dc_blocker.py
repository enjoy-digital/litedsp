#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, rounded, saturated, add_bypass

# DC Blocker ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDCBlocker(LiteXModule):
    """Multiplier-free 1st-order DC-removal IIR (per I/Q).

    ``y[n] = x[n] - x[n-1] + y[n-1] - (y[n-1] >> pole_shift)`` (pole at ``1 - 2**-pole_shift``,
    a notch at DC). Larger ``pole_shift`` -> notch closer to DC (slower settling). The feedback
    state is saturated for stability.

    With ``precision_bits = 0`` (default) the recursion runs at ``data_width`` and its DC
    rejection floors at the state quantization: the truncated leak ``y >> pole_shift`` is 0 for
    any ``y`` in ``[0, 2**pole_shift)``, so a DC step can leave a residual of up to
    ``2**pole_shift - 1`` LSBs (~``-6.02*(data_width - 1 - pole_shift)`` dBFS).

    With ``precision_bits = p > 0`` the recursive state/accumulator runs ``p`` bits wider
    (``p`` fractional bits) and the residual floor drops by ``6.02*p`` dB:

    - The leak is rounded away from zero (``|leak| >= 1`` whenever the state is nonzero), so
      the state has no truncation deadband: on constant input it decays to exactly 0 — a pure
      DC step settles to a residual of exactly 0 and silence produces no limit cycles.
    - The output requantization (wide state -> ``data_width``) uses first-order error
      feedback: the quantization error is fed back into the next quantization, giving a
      ``1 - z**-1`` noise transfer with a null at DC — the requantizer adds no DC bias
      (bounded by 1 LSB per averaging window, i.e. ``1/n`` LSB over ``n`` samples).
    - The remaining DC bound comes from the leak-rounding bias under AC excitation: the
      per-sample leak rounding error is < 1 wide LSB, so ``|mean(y_state)| <=
      2**pole_shift`` wide LSBs, i.e. residual DC ``<= 2**(pole_shift - p)`` output LSBs =
      ``-6.02*(data_width - 1 + p - pole_shift)`` dBFS (worst case; -108 dBFS at the default
      ``pole_shift=5`` with ``p=8``, 16-bit — measured values sit well below the bound since
      the rounding errors average out).

    ``precision_bits = 0`` is bit-identical to the original ``data_width``-wide recursion.

    Parameters
    ----------
    pole_shift : int
        Leaky-integrator pole position (pole = 1 - 2**-pole_shift); larger = narrower DC notch
        but slower settling. Implemented as a bare shift, so any value costs no multiplier.
    precision_bits : int
        Extra fractional bits of the recursive state (0 = legacy data_width-wide recursion,
        bit-identical). With p > 0 the output is requantized with first-order error feedback;
        residual DC is bounded by -6.02*(data_width - 1 + precision_bits - pole_shift) dBFS.
    """
    def __init__(self, data_width=16, pole_shift=5, precision_bits=0, with_csr=True):
        check(pole_shift >= 1,     "expected pole_shift >= 1")
        check(precision_bits >= 0, "expected precision_bits >= 0")
        self.data_width     = data_width
        self.pole_shift     = pole_shift
        self.precision_bits = precision_bits
        self.latency        = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Handshake.
        # ----------
        adv  = Signal()  # Output slot free or being consumed.
        xfer = Signal()  # An input sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        p = precision_bits
        for field in ["i", "q"]:
            x      = getattr(self.sink, field)
            x_prev = Signal((data_width, True))  # x[n-1].
            if p == 0:
                # Legacy data_width-wide recursion (bit-identical to pre-precision_bits builds).
                y_prev = Signal((data_width, True))  # y[n-1] (saturated feedback state).
                y_next = Signal((data_width, True))
                self.comb += y_next.eq(saturated(x - x_prev + y_prev - (y_prev >> pole_shift), data_width))
                # State advances only on real transfers, so bubbles never corrupt the recursion.
                self.sync += If(xfer,
                    x_prev.eq(x),
                    y_prev.eq(y_next),
                )
                self.sync += If(adv, getattr(self.source, field).eq(y_next))  # Bubbles masked by valid.
            else:
                # High-precision recursion: state carries p fractional bits (see class doc).
                W      = data_width + p
                y_wide = Signal((W, True))               # y[n-1] state, Qm.(n+p).
                e      = Signal((p, True))               # Error-feedback state, in [-2**(p-1), 2**(p-1)).
                leak   = Signal((W, True))
                y_next = Signal((W, True))
                s      = Signal((W + 1, True))
                q      = Signal((data_width + 1, True))  # Requantized output before saturation.
                self.comb += [
                    # Leak rounded away from zero: |leak| >= 1 whenever y != 0, so the state
                    # decays to exactly 0 (no truncation deadband -> no DC residual on a pure
                    # step, no limit cycles on silence).
                    leak.eq(Mux(y_wide < 0,
                        y_wide >> pole_shift,                          # Floor: <= -1 for y < 0.
                        (y_wide + (2**pole_shift - 1)) >> pole_shift,  # Ceil:  >= +1 for y > 0.
                    )),
                    y_next.eq(saturated(((x - x_prev) << p) + y_wide - leak, W)),
                    # First-order error feedback on the output requantization (noise transfer
                    # 1 - z**-1: a null at DC, so the p dropped bits add no DC bias).
                    s.eq(y_next + e),
                    q.eq(rounded(s, p)),
                ]
                self.sync += If(xfer,
                    x_prev.eq(x),
                    y_wide.eq(y_next),
                    e.eq(s - (q << p)),
                )
                self.sync += If(adv, getattr(self.source, field).eq(saturated(q, data_width)))

        # Output.
        # -------
        valid_pipe = Signal()  # Single register stage (latency = 1).
        self.sync += If(adv, valid_pipe.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid_pipe)

        # Bypass.
        # -------
        add_bypass(self)
