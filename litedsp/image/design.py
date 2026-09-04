#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side image maths: kernel presets, colour matrices, tone curves, Bayer mosaics."""

import numpy as np

from litedsp.common import check

# Kernel presets -----------------------------------------------------------------------------------

KERNEL_PRESETS = ("identity", "box3", "gaussian3", "gaussian5", "sharpen", "laplacian", "sobel_x",
                  "sobel_y", "emboss")

def kernel_preset(name="gaussian3", kernel_size=None, data_width=8):
    """``(coefficients, shift, offset)`` for :class:`LiteDSPKernel2D` (row-major, correlation
    with the ``w{row}{col}`` window). Signed-result kernels (Laplacian, Sobel, emboss) centre
    on ``2**(data_width - 1)``; ``box3`` uses ``7/64`` per tap (a 63/64 mean)."""
    check(name in KERNEL_PRESETS, f"expected name in {KERNEL_PRESETS}")
    mid = 1 << (data_width - 1)
    if name == "gaussian5":
        b = [1, 4, 6, 4, 1]
        coefficients = [b[i]*b[j] for i in range(5) for j in range(5)]
        K, shift, offset = 5, 8, 0
    else:
        K = 3
        table = {
            "identity":  ([0, 0, 0, 0, 1, 0, 0, 0, 0], 0, 0),
            "box3":      ([7]*9, 6, 0),
            "gaussian3": ([1, 2, 1, 2, 4, 2, 1, 2, 1], 4, 0),
            "sharpen":   ([0, -1, 0, -1, 5, -1, 0, -1, 0], 0, 0),
            "laplacian": ([0, 1, 0, 1, -4, 1, 0, 1, 0], 0, mid),
            "sobel_x":   ([-1, 0, 1, -2, 0, 2, -1, 0, 1], 0, mid),
            "sobel_y":   ([-1, -2, -1, 0, 0, 0, 1, 2, 1], 0, mid),
            "emboss":    ([-2, -1, 0, -1, 1, 1, 0, 1, 2], 0, 0),
        }
        coefficients, shift, offset = table[name]
    if kernel_size is not None:
        check(kernel_size == K, f"preset {name} is {K}x{K}")
    return coefficients, shift, offset

# Colour matrices ----------------------------------------------------------------------------------

COLOR_PRESETS = ("identity", "rgb_to_ycbcr_601", "ycbcr_to_rgb_601", "rgb_to_ycbcr_jpeg",
                 "ycbcr_to_rgb_jpeg",
                 "rgb_to_ycbcr_709", "ycbcr_to_rgb_709", "rgb_to_gray_601", "rgb_to_gray_709",
                 "select_r", "select_g", "select_b")

def color_preset(name="rgb_to_ycbcr_601", data_width=8, coeff_frac=12):
    """``(coefficients, in_offsets, out_offsets)`` for :class:`LiteDSPColorMatrix` (row-major
    3 x 3 or 1 x 3 in Q.coeff_frac, offsets in codes scaled by ``2**(data_width - 8)``):
    studio-range BT.601 / BT.709 (Y 16..235, chroma 128 centred), the full-range JPEG pair,
    grey conversions and channel selects."""
    check(name in COLOR_PRESETS, f"expected name in {COLOR_PRESETS}")
    s = 1 << (data_width - 8)
    q = lambda m: [int(round(v*(1 << coeff_frac))) for row in m for v in row]
    if name == "identity":
        return q([[1, 0, 0], [0, 1, 0], [0, 0, 1]]), (0, 0, 0), (0, 0, 0)
    if name in ("rgb_to_ycbcr_601", "rgb_to_ycbcr_709"):
        kr, kb = (0.299, 0.114) if name.endswith("601") else (0.2126, 0.0722)
        kg = 1 - kr - kb
        m = [[219/255*kr, 219/255*kg, 219/255*kb],
             [-224/255*kr/(2*(1 - kb)), -224/255*kg/(2*(1 - kb)), 224/255*0.5],
             [224/255*0.5, -224/255*kg/(2*(1 - kr)), -224/255*kb/(2*(1 - kr))]]
        return q(m), (0, 0, 0), (16*s, 128*s, 128*s)
    if name in ("ycbcr_to_rgb_601", "ycbcr_to_rgb_709"):
        kr, kb = (0.299, 0.114) if name.endswith("601") else (0.2126, 0.0722)
        kg = 1 - kr - kb
        y, c = 255/219, 255/224
        m = [[y, 0, c*2*(1 - kr)],
             [y, -c*2*(1 - kb)*kb/kg, -c*2*(1 - kr)*kr/kg],
             [y, c*2*(1 - kb), 0]]
        return q(m), (16*s, 128*s, 128*s), (0, 0, 0)
    if name == "rgb_to_ycbcr_jpeg":
        m = [[0.299, 0.587, 0.114], [-0.168736, -0.331264, 0.5], [0.5, -0.418688, -0.081312]]
        return q(m), (0, 0, 0), (0, 128*s, 128*s)
    if name == "ycbcr_to_rgb_jpeg":
        m = [[1, 0, 1.402], [1, -0.344136, -0.714136], [1, 1.772, 0]]
        return q(m), (0, 128*s, 128*s), (0, 0, 0)
    if name in ("rgb_to_gray_601", "rgb_to_gray_709"):
        kr, kb = (0.299, 0.114) if name.endswith("601") else (0.2126, 0.0722)
        return q([[kr, 1 - kr - kb, kb]]), (0, 0, 0), (0,)
    sel = {"select_r": [1, 0, 0], "select_g": [0, 1, 0], "select_b": [0, 0, 1]}[name]
    return q([sel]), (0, 0, 0), (0,)

# Tone curves --------------------------------------------------------------------------------------

def gamma_table(gamma=2.2, data_width=8):
    """``2**data_width`` entries of ``round(full * (x / full)**(1 / gamma))``."""
    full = (1 << data_width) - 1
    x = np.arange(1 << data_width)/full
    return [int(round(full*v**(1.0/gamma))) for v in x]

def contrast_table(contrast=1.0, brightness=0.0, data_width=8):
    """Linear tone curve ``clamp(contrast * (x - mid) + mid + brightness * full)``."""
    full = (1 << data_width) - 1
    mid  = full/2
    return [int(max(0, min(full, round(contrast*(x - mid) + mid + brightness*full))))
                                                 for x in range(1 << data_width)]

def equalize_table(histogram, data_width=8):
    """Histogram equalisation LUT from per-code counts (the CDF scaled to the code range)."""
    h = np.asarray(histogram, np.float64)
    full = (1 << data_width) - 1
    cdf = np.cumsum(h)
    if cdf[-1] == 0:
        return list(range(1 << data_width))
    cdf_min = cdf[cdf > 0][0]
    return [int(round((c - cdf_min)/max(cdf[-1] - cdf_min, 1)*full)) for c in cdf]

# Bayer --------------------------------------------------------------------------------------------

BAYER_PATTERNS = ("rggb", "bggr", "grbg", "gbrg")

def bayer_phase(pattern="rggb"):
    """``(row0col0, row0col1, row1col0, row1col1)`` colour indices (0 = R, 1 = G, 2 = B)."""
    check(pattern in BAYER_PATTERNS, f"expected pattern in {BAYER_PATTERNS}")
    return {"rggb": (0, 1, 1, 2), "bggr": (2, 1, 1, 0), "grbg": (1, 0, 2, 1),
            "gbrg": (1, 2, 0, 1)}[pattern]

def mosaic(rgb, pattern="rggb"):
    """Sample an (H, W, 3) image onto a Bayer mosaic (H, W)."""
    rgb = np.asarray(rgb)
    ph  = bayer_phase(pattern)
    out = np.zeros(rgb.shape[:2], rgb.dtype)
    for y in range(rgb.shape[0]):
        for x in range(rgb.shape[1]):
            out[y, x] = rgb[y, x, ph[2*(y & 1) + (x & 1)]]
    return out
