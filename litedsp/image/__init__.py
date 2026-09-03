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
