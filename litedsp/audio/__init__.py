#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio processing: level, dither, equalization, dynamics, effects, metering and audio I/O.

Conventions (see ``doc/audio.md``):

- Samples are signed Q1.(N-1) with ``data_width=24`` by default (Q1.23); blocks stay
  width-parameterized.
- Multi-channel audio is a channel-tagged TDM stream (``litedsp.common.tdm_layout``): one
  ``data`` sample plus a ``channel`` tag per beat (0 = left, 1 = right), frames are
  ``n_channels`` consecutive beats. Audio rates are far below the fabric clock, so one
  time-multiplexed engine serves every channel; ``n_channels=1`` degenerates to ``real_layout``.
- Serial engines document ``cycles_per_sample`` (clocks per beat) so the sample rate budget is
  explicit: e.g. a 3-band stereo EQ at 26 cycles per beat needs sys_clk >= 2.5 MHz at 48 kHz.
- Host-side design math (RBJ biquads, dB, time constants) lives in :mod:`litedsp.audio.design`.
"""

from litedsp.audio.dither   import LiteDSPDither
from litedsp.audio.dynamics import LiteDSPCompressor
from litedsp.audio.effects  import LiteDSPLFO, LiteDSPDelayLine, LiteDSPWetDryMix, LiteDSPReverb
from litedsp.audio.eq     import LiteDSPAudioEQ
from litedsp.audio.level  import LiteDSPVolume, LiteDSPStereoMatrix
