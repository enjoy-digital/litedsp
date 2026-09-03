#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Radar / sonar processing blocks: pulse timing and compression, MTI, corner turn, Doppler
processing, CFAR detection, peak extraction, target lists, tracking, beamforming and sonar gain
control (see doc/radar.md).

Conventions shared by the family:

- Samples are signed Q1.(N-1) I/Q on :func:`~litedsp.common.iq_layout`; cell values (magnitudes
  or powers) are unsigned on :func:`~litedsp.common.cell_layout`.
- A fast-time frame is one pulse (``first`` = range bin 0, ``last`` = bin N-1); a slow-time or
  range-Doppler frame is one range-bin column of M beats (pulses, or Doppler bins in natural FFT
  order); a CPI is N consecutive columns.
- Sparse streams (:func:`~litedsp.common.target_layout`, :func:`~litedsp.common.track_layout`)
  carry one burst per CPI closed by a terminator beat (``hit = 0``, count in ``data``/``hits``).
- Windowed blocks zero-pad at frame edges and flush their trailing outputs after ``last`` with
  ``sink.ready`` low (state-based, never a function of the block's own ``sink.valid``).
- Host-side math (CFAR thresholds, tracking gains, steering weights, TVG laws, unit
  conversions) lives in :mod:`litedsp.radar.design`; waveform references shared by gateware and
  golden models in :mod:`litedsp.radar.waveform`.
"""

from litedsp.radar.timing import LiteDSPRangeGate
from litedsp.radar.compress import LiteDSPPulseCompressor
from litedsp.radar.mti      import LiteDSPMTICanceller
from litedsp.radar.corner_turn import LiteDSPCornerTurn
from litedsp.radar.doppler  import LiteDSPDopplerProcessor
from litedsp.radar.cfar     import LiteDSPCACFAR, LiteDSPOSCFAR
from litedsp.radar.cfar_2d  import LiteDSPCFAR2D
from litedsp.radar.detect   import LiteDSPPeakExtractor, LiteDSPTargetList
from litedsp.radar.track    import LiteDSPAlphaBetaTracker
from litedsp.radar.clutter  import LiteDSPClutterMap
from litedsp.radar.kalman   import LiteDSPKalmanTracker
from litedsp.radar.beamform import LiteDSPBeamformer, LiteDSPMonopulse
from litedsp.radar.sonar    import LiteDSPTVG
