# Image / video processing blocks

`litedsp/image/` adds raster image processing to the library: a test-pattern source, LiteX video
interop, word packing for framebuffers, line-buffered 2-D operators (convolution kernels, Sobel,
rank filters, demosaicing), point operations (threshold, gain, tone LUTs, colour matrices),
geometry (box downscaling, cropping), per-frame measurements (statistics, histogram) and
composition (alpha / mask blending, box overlays). Every block follows the library conventions
(elastic `ready` / `valid` streams, bit-exact NumPy models, backpressured tests, Verilator
co-simulation, ECP5 budgets in [`resources.md`](resources.md), generated datasheets under
`blocks/`), plus the pixel conventions below. The end-to-end chain is exercised by
[AN012 — image pipeline](app_notes/an012_image_pipeline.md).

```
sensor -> PixelFromVideo -> Debayer -> PixelGain -> ColorMatrix -> Kernel2D / Sobel / RankFilter -> Threshold
             (LiteX video)   (RGGB)     (WB)       (RGB->YCbCr)      (line-buffered 3x3 / 5x5)         (edges)
                                          \-> PixelStats / PixelHistogram (AE / AWB / equalisation loops)
                                          \-> Downscaler / Crop -> PixelPack -> DMA / framebuffer
             AlphaBlend / BoxOverlay -> PixelToVideo (VTG-timed) -> display
```

## Pixel streams

| Layout | Fields | Notes |
|---|---|---|
| `pixel_layout(dw)` | `data` (unsigned), `eol` | mono / raw Bayer / Y / mask |
| `pixel_layout(dw, 3)` | `r`, `g`, `b` (unsigned), `eol` | RGB; YCbCr rides on the same fields |
| `window_layout(dw, nc, K)` | `w{row}{col}` (channels packed LSB-first), `eol` | line-buffer output, `w{P}{P}` is the pixel |
| `video_layout(dw)` | `hsync`, `vsync`, `de`, `r`, `g`, `b` | = LiteX `video_data_layout` (blanking beats) |
| `video_timing_layout(cb)` | `hsync`, `vsync`, `de`, `hres`, `vres`, `hcount`, `vcount` | = LiteX `video_timing_layout` |

- **Framing.** `first` marks the first pixel of a frame, `last` its last pixel and `eol` the last
  pixel of every line. No coordinates ride the stream: consumers derive them with
  `LiteDSPPixelCounter` (`col`, `row`, the learned `width` / `height`; `first` re-synchronises
  unconditionally and reset counts as a frame start, so unframed harness streams still flow).
- **Geometry rule: consumers derive, producers configure.** Blocks that generate or cut a
  raster (pattern source, video adapters, unpack, crop, downscaler) take `width` / `height`
  defaults plus a runtime geometry CSR; line-buffer blocks size their RAMs with `max_width` and
  learn the live line length per frame, flagging a longer line or a mid-frame change with the
  sticky `geometry_error` (re-synchronised at the next `first`). Geometry mismatches surface as
  flags, never as hangs.
- **Codes.** Unsigned 4..16-bit pixel codes; signed intermediates through `pixel_signed`,
  results `rounded` then `clamped` to the code range with sticky `sat` flags where a clamp can
  happen. Kernel coefficients are signed `coeff_width` with a runtime right shift and signed
  offset; colour matrices are signed Q4.12; gains unsigned Q4.8 (256 = 1.0); alpha is 9-bit
  (256 = 1.0).
- **Frame-atomic tables.** Kernel coefficients, colour matrices, crop ROIs and overlay boxes
  live in shadow tables written through an index register and copied to the active set at the
  next accepted `first` (`commit`, `commit_pending`), or immediately (`commit_now`) where a
  mid-frame change is acceptable; the committing beat already uses the new set. LUT entries load
  at any time (a mid-frame load is visible mid-frame).

## 2-D blocks

`LiteDSPLineBuffer` is the building block: `kernel_size - 1` line RAMs (`max_width` deep, read
before write) and the incoming pixel form a column that shifts into `K x K` window registers, so
output beat k carries the neighbourhood of input pixel k with its framing. Borders are
`replicate` (edge pixel), `mirror` (`p[-1] = p[1]`, keeps a Bayer phase) or `zero`, applied by
output-side muxes from the output coordinates, the learned width and the frame height. After every
line the block pushes `P = K // 2` virtual columns and after every frame `P` virtual lines
(`sink.ready` low meanwhile) so the trailing outputs come out on their own; the stream stays
1:1 with a throughput of `width / (width + P)` (the blanking of a video source covers it).
`latency = P * (width + P) + P + 3` at the build width. The kernel, Sobel, rank filter and debayer
blocks wrap it (`+2` / `+3` / `+4` / `+2` cycles).

| Geometry | mono 3x3 | RGB 3x3 | RGB 5x5 |
|---|---|---|---|
| 640 x 480 | 2 x 640 x 8 bit = 1 EBR | 3 EBR | 6 EBR |
| 1280 x 720 | 2 EBR | 6 EBR | 12 EBR |
| 1920 x 1080 | 2 EBR | 6 EBR | 12 EBR |

(ECP5 EBR = 18 kbit; the border muxes of a 5x5 RGB window are the LUT-heavy part, see
`resources.md`.) One pixel per clock; the blocks are built for the 100 MHz ECP5 landing, 1080p60
(148.5 MHz) needs registered adder trees and is a follow-up.

Parallel branches around a 2-D block (a blend of the filtered and original images) need the
original to run `P * width + ...` beats ahead: put a `LiteDSPPixelFIFO` on the direct branch, or let
the flow insert one (`auto_delay`: delays deeper than 32 beats become FIFOs, see `flow.md`).
The generic latency / bypass test harnesses never send `last`, so 2-D blocks are excluded from
them and pin their latency and bypass in their own tests; their co-simulation is always framed.

## Blocks

| Block | Key(s) | Role | Latency |
|---|---|---|---|
| `LiteDSPPixelPattern` | `pixel_pattern` | const / ramp / colour bars / checker / counter / Bayer test frames, one-shot or continuous | source |
| `LiteDSPPixelFromVideo` / `LiteDSPPixelToVideo` | `pixel_from_video`, `pixel_to_video` | LiteX video streams in (blanking consumed, framing from syncs, geometry error) and out (VTG-paced, black on underflow, re-sync on `first`) | 1 |
| `LiteDSPPixelPack` / `LiteDSPPixelUnpack` | `pixel_pack`, `pixel_unpack` | rgb888 / xrgb8888 / rgb565 / mono words, `eol` regenerated on unpack | 0 / 1 |
| `LiteDSPLineBuffer` | `line_buffer` | K x K windows with borders | `P (W + P) + P + 3` |
| `LiteDSPPixelFIFO` | `pixel_fifo` | elastic buffer for parallel branches | 0 |
| `LiteDSPKernel2D` | `kernel_2d`, `kernel_5x5`, `gaussian_blur`, `sharpen`, `laplacian` | correlation kernel, shadow coefficients, presets, bypass | LB + 2 |
| `LiteDSPSobel` | `sobel` | gradient magnitude (L1 / L-inf / approx) and quantised direction | LB + 3 |
| `LiteDSPRankFilter` | `rank_filter`, `erode`, `dilate` | 3x3 sorting network, runtime rank | LB + 4 |
| `LiteDSPDebayer` | `debayer` | bilinear demosaic, runtime phase | LB + 2 |
| `LiteDSPThreshold` | `threshold` | scan-line hysteresis, invert, bypass | 1 |
| `LiteDSPPixelGain` | `pixel_gain` | per-channel gain / offset (white balance, brightness / contrast) | 2 |
| `LiteDSPPixelLUT` | `pixel_lut`, `gamma` | per-channel or shared tone tables, host-loaded | 1 |
| `LiteDSPColorMatrix` | `color_matrix`, `rgb_to_ycbcr`, `ycbcr_to_rgb`, `rgb_to_gray` | 3x3 / 1x3 matrix with offsets, presets | 3 |
| `LiteDSPDownscaler` | `downscaler` | exact box mean by 2 / 4 / 8 | 2 (rate changer) |
| `LiteDSPCrop` | `crop` | region of interest | 1 (rate changer) |
| `LiteDSPPixelStats` | `pixel_stats` | sum / min / max / count / zone sums per frame, IRQ | 0 (tap) |
| `LiteDSPPixelHistogram` | `pixel_histogram` | per-frame histogram streamed after `last` | variable |
| `LiteDSPAlphaBlend` | `alpha_blend`, `mask_blend` | lock-step blend with a constant or mask alpha | 1 |
| `LiteDSPBoxOverlay` | `box_overlay` | rectangle outlines from a host table | 1 |

## Host side

`litedsp.image.design` holds the pure-Python maths: kernel presets (`kernel_preset`), colour
matrices (`color_preset`: BT.601 / BT.709 studio, JPEG full range, grey, selects), tone tables
(`gamma_table`, `contrast_table`, `equalize_table` from a histogram) and the Bayer helpers
(`bayer_phase`, `mosaic`). The typed drivers (`PixelPatternDriver`, `ImageKernelDriver`,
`RankFilterDriver`, `ThresholdDriver`, `PixelGainDriver`, `PixelLUTDriver`, `ColorDriver`,
`CropDriver`, `PixelStatsDriver`, `AlphaBlendDriver`, `BoxOverlayDriver` in
`litedsp/software/drivers.py`) wrap the CSR maps; the flow's manifest discovery picks them by
registry key. Control loops: auto-exposure from `PixelStatsDriver.exposure_error`, grey-world
white balance through `PixelGainDriver.gray_world(means)`, histogram equalisation by feeding the
streamed histogram to `PixelLUTDriver.equalize`.

## LiteX video interop

`video_layout` equals the LiteX `video_data_layout` (asserted by a guarded unit test) and
`video_timing_layout` the LiteX timing stream, so `LiteDSPPixelFromVideo` sits behind a LiteX
video input (or a `VideoTimingGenerator` + pattern for tests) and `LiteDSPPixelToVideo` in front
of a LiteX PHY, paced by the timing generator: an active beat without a pixel outputs black and
sets the sticky, counted `underflow` (optional interrupt); stale pixels are dropped while
synchronising and during the vertical blanking so a starved frame recovers by the next one.
Framebuffer paths use `LiteDSPPixelPack` / `LiteDSPPixelUnpack` with the LiteX word formats.

## Verification

Every block has a bit-exact integer model in `test/models.py` and a `test/test_*.py` that runs
it on 16 x 12 frames under random backpressure (`sink_throttle=0.2`, `source_ready_rate=0.7`)
plus functional bounds (Sobel step responses, Gaussian of a constant, morphology sizes, JPEG round
trips within 1 LSB, gradient reconstruction PSNR, overrun / underflow / geometry flags, frame-atomic
commits). All keys but the timing-paced `pixel_to_video`, the CSR-only `pixel_stats` and the
plumbing (`pixel_pack`, `pixel_unpack`, `pixel_fifo`) are co-simulated with Verilator on framed
rasters (`sim/run_blocks.py`); rate-changing blocks compute their expected output count from the
model. Nightly line coverage above 90 % or a waiver naming the semantic tests (the shadow-table
and bypass arms of the kernel, colour matrix and pattern source, the border arms of the line
buffer and debayer).

## Roadmap

Rational bilinear scaling (after the box downscaler), 4:2:2 chroma subsampling for a JPEG path,
frame difference / temporal noise reduction (frame store in SRAM), run-length encoding, an 8x8
DCT, a detection-list sink for the overlay (shared with the radar target stream) and registered
adder trees for 1080p60.
