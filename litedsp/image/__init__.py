#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Image / video processing blocks.

Pixels ride :func:`litedsp.common.pixel_layout` streams (unsigned codes, ``first`` / ``eol`` /
``last`` framing, no coordinates); 2-D blocks build their neighbourhoods from line buffers;
LiteX video streams enter and leave through the adapters in ``video.py``. See ``doc/image.md``.
"""

from litedsp.image.common import LiteDSPPixelCounter
from litedsp.image.pattern import LiteDSPPixelPattern
from litedsp.image.adapt   import LiteDSPPixelPack, LiteDSPPixelUnpack
from litedsp.image.video   import LiteDSPPixelFromVideo, LiteDSPPixelToVideo
from litedsp.image.linebuffer import LiteDSPLineBuffer
from litedsp.image.stream  import LiteDSPPixelFIFO
from litedsp.image.kernel  import LiteDSPKernel2D
from litedsp.image.edge    import LiteDSPSobel
from litedsp.image.rank    import LiteDSPRankFilter
from litedsp.image.point   import LiteDSPThreshold, LiteDSPPixelGain
from litedsp.image.lut     import LiteDSPPixelLUT
from litedsp.image.color   import LiteDSPColorMatrix
from litedsp.image.debayer import LiteDSPDebayer
from litedsp.image.scale   import LiteDSPDownscaler, LiteDSPCrop
