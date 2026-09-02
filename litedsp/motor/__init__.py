#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Motor control: reference-frame transforms, current/speed regulators, SVPWM/PWM, sensor
interfaces (encoder, Hall, sigma-delta current sense), observers, resolver and the FOC composite.

Per-unit conventions (shared by every block, the golden models and the PMSM example):

- Currents/voltages are signed Q1.(N-1) per-unit samples: ``1.0`` = the base current ``I_b``
  (e.g. the inverter's peak-current rating) or base voltage ``V_b`` (``V_dc/2``, the maximum
  sinusoidal phase peak without over-modulation).
- Electrical angle streams (``angle_layout``) are signed with a full turn = ``2**angle_width``
  (the CORDIC/NCO convention); speed is angle units per control period.
- The control period ``Ts`` is one PWM period: :class:`LiteDSPPWM` accepts one duty sample per
  period, so backpressure paces the whole loop.
- Loop gains are runtime signed Q4.12 (``gain_width=16``, ``gain_frac=12``); per-unit plant
  constants (``R``, ``L``, ``psi``) follow the same scale.
"""

from litedsp.motor.transforms import (LiteDSPClarke, LiteDSPInverseClarke, LiteDSPSinCos,
    LiteDSPAngleRamp, LiteDSPPark, LiteDSPInversePark)
