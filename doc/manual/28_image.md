# Image and video blocks {#image}

The image family adds raster image processing to LiteDSP: a test-pattern source, LiteX video
interoperability, word packing for frame buffers, line-buffered 2-D operators (kernels, Sobel, rank
filters, demosaicing), point operations (threshold, gain, tone tables, colour matrices), geometry
(box downscaling, cropping), per-frame measurements (statistics, histogram) and composition (alpha
and mask blending, box overlays). This chapter is for the engineer who builds a camera or display
pipeline from these blocks.

The concepts are explained in [Images and video in a nutshell](#image-primer). The blocks follow
the common contract of [Block contract](#architecture): elastic ready/valid streams, bit-exact
NumPy golden models, backpressured tests. This chapter adds what is specific to the family: the
pixel streams, the geometry rule, the line buffer and the frame-atomic tables.

## At a glance {#img-glance}

| Item | Value |
|------------------------|------------------------------------------------------------------|
| Directory | `litedsp/image/` (20 files) |
| Blocks | 32 registry entries, category `image` (21 classes and their presets) |
| Stream layouts | `pixel_layout`, `window_layout`, `video_layout`, `video_timing_layout` |
| Pixel codes | Unsigned, 4 to 16 bits, 8 by default |
| Host helpers | `litedsp.image.design` |
| Drivers | 11 typed drivers in `litedsp/software/drivers.py` |
| Example | `examples/image_pipeline.py` (AN012), `examples/image_core.yml` |
| Status | See [status](#intro-status) |
| Registers | See [Image registers](#reg-image) |

Each block also has a generated datasheet in the online catalogue
([index](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md)).

## A camera pipeline {#img-chain}

The figure below shows a typical camera front end built from the family. A LiteX video input or
a raw sensor stream enters as pixels; the debayer, the gain and the colour matrix produce a
balanced YCbCr image; a 2-D filter and a threshold produce an edge map. Statistics and a
histogram measure the stream for the host's control loops.

![A camera front end. The debayer and the 2-D filter are line-buffered blocks; the others are
point operations. The statistics block sits in line with zero latency and measures what it
passes; the histogram streams its bins after each frame.](img_chain.svg)

The same blocks also serve the output side: downscaling and cropping before a frame buffer
(`LiteDSPPixelPack` into memory words), or blending, overlays and `LiteDSPPixelToVideo` before a
display.

## Pixel streams {#img-streams}

The table below lists the layouts of `litedsp/common.py` that the family uses.

| Layout | Fields | Use |
|------------------------------------------|------------------------|----------------------------------|
| `pixel_layout(dw)` | `data`, `eol` | Mono, raw Bayer, luma or mask |
| `pixel_layout(dw, 3)` | `r`, `g`, `b`, `eol` | RGB; YCbCr rides on the same fields |
| `window_layout(dw, nc, K)` | `w{row}{col}`, `eol` | Line-buffer output, `w{P}{P}` is the pixel |
| `video_layout(dw)` | `hsync`, `vsync`, `de`, `r`, `g`, `b` | LiteX `video_data_layout` |
| `video_timing_layout(cb)` | `hsync`, `vsync`, `de`, `hres`, `vres`, `hcount`, `vcount` | LiteX `video_timing_layout` |

`first` marks the first pixel of a frame, `last` its last pixel and `eol` the last pixel of every
line. No coordinates ride the stream: a block that needs them derives them with
`LiteDSPPixelCounter`, which outputs `col`, `row` and the learned `width` and `height`.

`first` re-synchronizes the counter unconditionally, and reset counts as a frame start, so an
unframed test stream still flows.

In a window, the channels of each neighbour are packed LSB first, `n_channels x data_width` bits
per field. `video_layout` and `video_timing_layout` are field-compatible with the LiteX video
streams; a guarded unit test asserts it.

## Geometry, codes and tables {#img-rules}

Three rules hold for the whole family.

**Consumers derive, producers configure.** Blocks that generate or cut a raster (pattern source,
video adapters, unpack, crop, downscaler) take `width` and `height` defaults plus runtime geometry
registers.

Line-buffered blocks size their RAMs with `max_width` and learn the live line length per frame. A
line longer than `max_width` or a length change inside a frame sets the sticky `geometry_error`, and
the block re-synchronizes at the next `first`. A geometry mismatch shows as a flag, never as a hang.

**Codes are unsigned and clamped.** Pixel codes are 4 to 16 bits. Intermediates are signed and wide;
results are rounded half up, then clamped to the code range, with a sticky `sat` flag where a clamp
can happen.

Kernel coefficients are signed `coeff_width` bits with a runtime right shift and signed offset;
colour matrices are signed Q4.12; gains are unsigned Q4.8 (256 = 1.0); the blend factor is 9 bits
(256 = 1.0).

**Tables change between frames.** Kernel coefficients, colour matrices, crop regions and overlay
boxes live in *shadow tables*. The host writes them through an index register; `commit` copies them
to the active set at the next accepted `first` (`commit_pending` reads high meanwhile), or
`commit_now` copies them at once.

The committing beat already uses the new set. LUT entries are the exception: they load at any time,
so a load in the middle of a frame shows in that frame.

## The line buffer {#img-linebuffer}

`LiteDSPLineBuffer` is the building block of every 2-D operator. `kernel_size - 1` line RAMs,
`max_width` deep and read before write, hold the previous lines.

The incoming pixel and the RAM reads form a column that shifts into `K x K` window registers. Output
beat `k` carries the neighbourhood of input pixel `k`, with its framing, as the figure below shows
for `K = 3`.

![Line buffer for a 3 x 3 window. The pixel enters line RAM 1, whose output enters line RAM 2;
the pixel and the two RAM outputs form one column of the window registers. Border muxes replace
the neighbours that fall outside the image.](img_linebuffer.svg)

The borders are applied by muxes on the output side, from the output coordinates, the learned
width and the frame height.

| `border` | Missing neighbour | Use |
|-------------|------------------------------------------|----------------------------------|
| `replicate` | The edge pixel | Default of most blocks |
| `mirror` | `p[-1] = p[1]` | Keeps the Bayer phase, default of the debayer |
| `zero` | 0 | Morphology, zero-padded kernels |

After every line, the block pushes `P = K // 2` virtual columns, and after every frame `P`
virtual lines, with `sink.ready` low. The trailing outputs therefore come out on their own and
the stream stays one output per input. The throughput is `width / (width + P)`; the blanking of
a video source covers the difference.

The latency is `P * (width + P) + P + 3` cycles at the build `width`: 37 cycles for a 3 x 3
window on 32-pixel lines, 645 on 640-pixel lines. The kernel, debayer, Sobel and rank blocks add
2, 2, 3 and 4 cycles of arithmetic.

| Parameter | Default | Meaning |
|---------------|-------------|---------------------------------------------------|
| `kernel_size` | 3 | Window size K: 3, 5 or 7 |
| `n_channels` | 1 | 1 (mono) or 3 (RGB) |
| `width` | 640 | Build width, used for the declared latency |
| `max_width` | None | RAM depth, `width` when None |
| `border` | `replicate` | `replicate`, `mirror` or `zero` |

The RAMs hold `(K - 1) x max_width` pixels of `n_channels x data_width` bits, the border muxes of
a large RGB window are the LUT-heavy part. The out-of-context results of
[Image results](#perf-image) give both for the budgeted configurations.

## Parallel branches {#img-branches}

A blend of the filtered image with the original needs the two branches in lock step. The original
branch must then run about `P * width` beats ahead of the 2-D block, so it needs a buffer that deep.

Put a `LiteDSPPixelFIFO` on the direct branch, or let the flow insert one: its automatic delay
balancing turns delays deeper than 32 beats into FIFOs ([Flow, generator, GUI and host
software](#tooling)).

## 2-D operators {#img-2d}

Four blocks wrap the line buffer.

The kernel computes a correlation per channel, `sum(coef[i][j] * w[i][j])`, then
`clamped(rounded(acc, shift) + offset)` (`LiteDSPKernel2D`). The coefficients are signed
`coeff_width` bits, 10 by default, row-major with `coef[0][0]` on the top-left neighbour.

They live in a shadow table loaded through `coeff_index`, which auto-increments on each write;
`shift` (0 to 15) and `offset` are runtime. `bypass` outputs the window centre at the same latency.

`kernel_preset(name)` gives `(coefficients, shift, offset)` for `identity`, `box3`, `gaussian3`,
`gaussian5`, `sharpen`, `laplacian`, `sobel_x`, `sobel_y` and `emboss`. The kernels with a signed
result centre it on half scale. The registry keys `gaussian_blur`, `sharpen`, `laplacian` and
`kernel_5x5` are the kernel with a preset.

The Sobel block computes `gx` and `gy` with adders only and a runtime magnitude `mode`
(`LiteDSPSobel`): `l1` for `|gx| + |gy|`, `linf` for the larger of the two, `approx` for
`max + min/4`. The result is `clamped(rounded(mag, shift))`; the default `shift=3` maps the
largest L1 value onto the code range. `with_direction` adds a 2-bit quantized edge direction.

The rank filter sorts the 3 x 3 window with a 36-comparator odd-even transposition network and
outputs the runtime `rank` (`LiteDSPRankFilter`): 0 is erosion, 4 the median, 8 dilation. The
keys `erode` and `dilate` are the rank filter with rank 0 and 8.

The debayer demosaics a raw mono stream into RGB by bilinear interpolation (`LiteDSPDebayer`). The
colour of each site follows the output coordinate parity, combined with a runtime 2-bit `phase` for
cropped sensors, from the build-time `pattern` (`rggb` by default).

Red and blue sites take the centre and the means of the edge and corner neighbours; green sites take
the centre and the means along and across the row.

## Point operations {#img-point}

The point operations look at one pixel at a time and have a fixed, short latency.
The threshold (`LiteDSPThreshold`, controls `high`, `low`, `invert`), the gain and offset per
channel (`LiteDSPPixelGain`), the code-to-code table (`LiteDSPPixelLUT`) and the 3 x 3 or 1 x 3
colour matrix (`LiteDSPColorMatrix`, shadow table) all have a `bypass`; their latencies are in
[Block summary](#img-blocks).

The threshold outputs full scale at or above `high`, zero below `low`, and keeps its previous
decision in between; the state resets at `first` and at every `eol`, and `low = high` gives a plain
threshold.

The gain computes `clamped(rounded(x * gain, 8) + offset)` with unsigned Q4.8 gains and signed
offsets. The LUT initializes to the `gamma` curve
of its constructor, identity for 1.0; the key `gamma` is a LUT built with gamma 2.2.

The colour matrix computes `y_c = clamped(rounded(sum_k m[c][k] (x_k - in_off_k), 12) +
out_off_c)`. Its shadow table holds the nine coefficients at indexes 0 to 8, then three input
and three output offsets. `color_preset(name)` gives BT.601 and BT.709 studio range, JPEG full
range, grey and channel selects; the keys `rgb_to_ycbcr`, `ycbcr_to_rgb` and `rgb_to_gray` are
the BT.601 presets. `bypass` exists only with `n_out = 3`.

## Geometry {#img-geometry}

The downscaler computes the exact box mean of each `D x D` tile, with `D` = 2, 4 or 8
(`LiteDSPDownscaler`). Pixels accumulate along the line over `D` columns, and the partial sums
accumulate down the tile in a RAM indexed by the tile column.

Each tile emits `rounded(sum, 2 log2 D)` on its last pixel. Partial tiles at the right and bottom
edges are dropped; the output is reframed from the tile counters.

The crop passes a region of interest and consumes the rest (`LiteDSPCrop`). The region, `x0`,
`y0`, `roi_width` and `roi_height`, is a shadow table committed at the next `first`. A region
that extends beyond the learned frame sets the sticky `geometry_error`.

Both are rate changers: fewer output beats than input beats, with their own `first`, `eol` and
`last`. Their latency, 2 and 1, counts from the input pixel that completes an output.

## Measurements {#img-measure}

The statistics block is a zero-latency passthrough that measures one channel per frame
(`LiteDSPPixelStats`). It accumulates `sum`, `min`, `max` and `count` over the frame and the sums
of `zones x zones` zones, 4 x 4 by default, from the runtime zone size. It latches them at `last`,
with the optional `ev.frame` interrupt; the host computes the mean.

The histogram counts one channel per frame into `2**bins_log2` bins, the top bits of the code
(`LiteDSPPixelHistogram`). It counts at one pixel per clock in a ping-pong RAM.

At `last` it seals a bank and streams its bins out, one beat per bin from `first` on bin 0 to `last`
on the final bin, while clearing them. A frame that ends before the previous histogram drained sets
the sticky `overrun`.

## Composition {#img-blend}

The alpha blend computes `y = rounded(a A + (256 - a) B, 8)` per channel on two lock-stepped
streams (`LiteDSPAlphaBlend`). `a` is the 9-bit runtime `alpha`, or a third mono stream with
`with_alpha_sink` (the key `mask_blend`), whose full scale maps to 256. The framing comes from
`sink_a`. A value of the `alpha` register above 256 saturates to 256, that is 1.0.

The box overlay draws up to `n_boxes` rectangle outlines (`LiteDSPBoxOverlay`). Each box has two
inclusive corners, a colour and an enable bit, in a shadow table committed at the next `first`.
The runtime `thickness` (1 to 15) sets the outline width, and the lowest enabled box wins where
outlines overlap.

## Sources, video and memory {#img-io}

The pattern source generates framed test rasters (`LiteDSPPixelPattern`). Its runtime `mode`
selects a constant, a ramp, eight colour bars, an 8 x 8 checkerboard, a pixel counter, or the
colour bars sampled on an RGGB mosaic. It streams frames back to back when enabled, or one frame
per trigger; `width` and `height` are runtime.

`LiteDSPPixelFromVideo` sits behind a LiteX video input, or a `VideoTimingGenerator` with a
pattern in tests. It consumes the blanking beats and frames the active pixels from the syncs. A
line shorter or longer than `width` sets the sticky `geometry_error`.

`LiteDSPPixelToVideo` sits in front of a LiteX video PHY, paced by the timing generator through its
`vtg_sink`. Each timing beat produces one video beat; each active beat pulls one pixel.

An active beat without a pixel outputs black and sets the sticky, counted `underflow` (optional
interrupt). Stale pixels are dropped while it synchronizes on a frame start, so a starved frame
recovers by the next one.

`LiteDSPPixelPack` and `LiteDSPPixelUnpack` convert pixels to and from memory words for frame
buffers, in the formats `rgb888`, `xrgb8888`, `rgb565` and `mono`. Pack is combinational and
drops `eol`; unpack regenerates `eol` from a column counter and the runtime `width`.

## Block summary {#img-blocks}

The table below lists every class of the family with its registry keys and its declared latency;
`LB` is the line-buffer latency of [The line buffer](#img-linebuffer).

| Block | Keys | Latency |
|------------------------------------|----------------------------------------|------------------------|
| `LiteDSPPixelPattern` | `pixel_pattern` | Source |
| `LiteDSPPixelFromVideo` | `pixel_from_video` | 1 |
| `LiteDSPPixelToVideo` | `pixel_to_video` | 1, paced by the timing |
| `LiteDSPPixelPack` | `pixel_pack` | 0 |
| `LiteDSPPixelUnpack` | `pixel_unpack` | 1 |
| `LiteDSPLineBuffer` | `line_buffer` | LB |
| `LiteDSPPixelFIFO` | `pixel_fifo` | 0 |
| `LiteDSPKernel2D` | `kernel_2d`, `kernel_5x5`, `gaussian_blur`, `sharpen`, `laplacian` | LB + 2 |
| `LiteDSPSobel` | `sobel` | LB + 3 |
| `LiteDSPRankFilter` | `rank_filter`, `erode`, `dilate` | LB + 4 |
| `LiteDSPDebayer` | `debayer` | LB + 2 |
| `LiteDSPThreshold` | `threshold` | 1 |
| `LiteDSPPixelGain` | `pixel_gain` | 2 |
| `LiteDSPPixelLUT` | `pixel_lut`, `gamma` | 1 |
| `LiteDSPColorMatrix` | `color_matrix`, `rgb_to_ycbcr`, `ycbcr_to_rgb`, `rgb_to_gray` | 3 |
| `LiteDSPDownscaler` | `downscaler` | 2, rate changer |
| `LiteDSPCrop` | `crop` | 1, rate changer |
| `LiteDSPPixelStats` | `pixel_stats` | 0 |
| `LiteDSPPixelHistogram` | `pixel_histogram` | None |
| `LiteDSPAlphaBlend` | `alpha_blend`, `mask_blend` | 1 |
| `LiteDSPBoxOverlay` | `box_overlay` | 1 |

The registry builds the 2-D blocks at `width=64` for its reflection; a design sets `width` and
`max_width` for its own lines.

## Host side {#img-host}

`litedsp.image.design` holds the host maths in pure Python: kernel and colour presets, tone tables
(gamma, contrast, equalization from a histogram) and the Bayer helpers. The table below lists the
typed drivers of `litedsp/software/drivers.py`.

| Driver | Block | Main methods |
|--------------------------------|----------------------|----------------------------------------------|
| `PixelPatternDriver` | Pattern source | `set_mode`, `set_geometry`, `set_const`, `start`, `trigger` |
| `ImageKernelDriver` | Kernel | `set_coefficients`, `set_preset`, `commit`, `set_bypass` |
| `RankFilterDriver` | Rank filter | `set_mode`, `set_bypass` |
| `ThresholdDriver` | Threshold | `set_levels`, `set_invert` |
| `PixelGainDriver` | Pixel gain | `set_gains`, `set_white_balance`, `gray_world` |
| `PixelLUTDriver` | LUT | `load`, `set_gamma`, `equalize` |
| `ColorDriver` | Colour matrix | `set_matrix`, `set_preset`, `commit` |
| `CropDriver` | Crop | `set_roi` |
| `PixelStatsDriver` | Statistics | `read_frame`, `zones`, `exposure_error` |
| `AlphaBlendDriver` | Alpha blend | `set_alpha` |
| `BoxOverlayDriver` | Box overlay | `set_boxes`, `commit` |

The three control loops of [Statistics and control loops](#ipri-stats) map onto these drivers.
Auto exposure uses `PixelStatsDriver.exposure_error(target)`, the log2 ratio of the target mean
to the frame mean. Grey-world white balance passes the channel means to
`PixelGainDriver.gray_world(means)`. Histogram equalization feeds the streamed histogram to
`PixelLUTDriver.equalize(histogram)`.

```python
from litex import RemoteClient
from litedsp.software.drivers import PixelStatsDriver, PixelGainDriver, ColorDriver

bus = RemoteClient()
bus.open()
csc = ColorDriver(bus, "csc")
csc.set_preset("rgb_to_ycbcr_601")
csc.commit()                            # Applied at the next frame start.
stats = PixelStatsDriver(bus, "stats")
print(stats.read_frame())               # sum, min, max, count, mean of the last frame.
print(stats.exposure_error(target=118)) # Positive: under-exposed.
```

The prefixes `csc` and `stats` are the names of the blocks in the SoC; with a standalone core,
`discover()` reads them from the `blocks.json` manifest ([Flow, generator, GUI and host
software](#tooling)).

## Standalone image core {#img-core}

`examples/image_core.yml` describes a standalone camera core for `litedsp_gen`: raw RGGB in,
BT.601 YCbCr out, through a debayer sized for 640-pixel lines, a white-balance pixel gain and the
`rgb_to_ycbcr` matrix, driven over AXI-Lite by `PixelGainDriver` and `ColorDriver`. [The image
core](#apps-image-core) shows its generation.

## Verification {#img-verification}

Every block has a bit-exact integer model in `test/models.py` and a unit test that runs it on
16 x 12 frames under random backpressure. Functional bounds come on top: Sobel step responses, a
Gaussian of a constant, morphology sizes, JPEG round trips within 1 LSB, gradient reconstruction
PSNR, overrun, underflow and geometry flags, frame-atomic commits. The generic latency and bypass
harnesses never send `last`, which a 2-D block needs to flush its last lines, so the 2-D blocks
check their latency and bypass in their own tests.

Every key except five is co-simulated with Verilator on framed rasters (`sim/run_blocks.py`).
The exceptions are the timing-paced `pixel_to_video`, the register-only `pixel_stats` and the
plumbing `pixel_pack`, `pixel_unpack` and `pixel_fifo`. Rate-changing blocks compute their
expected output count from the model.

Nightly line coverage is above 90 % for every key, or a waiver in `sim/coverage_waivers.json` names
the semantic tests. The waived arms are the shadow-table and bypass arms of the kernel, the colour
matrix, the box overlay and the pattern source, and the border arms of the line buffer and the
debayer.

## Application note: image pipeline {#img-an012}

`examples/image_pipeline.py` (AN012) assembles the family into a small camera front end and runs
it on a synthetic scene. Every block is the real gateware on `pixel_layout` streams. After the
colour matrix, a split feeds two branches.

| Stage | Blocks |
|--------------|------------------------------------------------------------------------|
| Front end | Debayer, pixel gain (white balance), colour matrix (RGB to YCbCr, JPEG) |
| Branch A | Histogram of Y, 256 bins |
| Branch B | Colour matrix (select Y), Gaussian 3 x 3, Sobel (L1, shift 2), threshold 96 / 64, histogram (edge or not) |

The scene is a 32 x 24 RGB image (colour bars over a ramp, a bright triangle); the sensor model
scales red by 0.6 and blue by 0.8, adds noise and samples an RGGB mosaic. Two identical frames are
streamed free flowing, then under random backpressure.

| Gate | Value |
|-------------|-----------------------------------------------------------------------------|
| YCbCr frame | Bit-exact against the model chain; PSNR at least 40 dB against the float matrix |
| Edge map | Bit-exact against the model chain; at least 95 % agreement with a float Gaussian and Sobel; 2 % to 50 % edge pixels |
| Histograms | Both sum to 768 pixels and equal the NumPy count; frame 2 equals frame 1 |
| Latency | Branch B's first output, at full rate, lands exactly the declared latency after its first input |

```sh
python3 examples/image_pipeline.py --plot-dir /tmp/an012
```

```console
[free-flow] YCbCr bit-exact True, PSNR 59.0 dB vs float; edge map bit-exact True, 97.4 % agreement with the float Sobel; histograms 768 / 768 px (edge pixels 29); branch-B latency 83 (declared 83); frame 2 == frame 1 True
[backpressure] YCbCr bit-exact True, PSNR 59.0 dB vs float; edge map bit-exact True, 97.4 % agreement with the float Sobel; histograms 768 / 768 px (edge pixels 29); branch-B latency 107 (declared 83); frame 2 == frame 1 True
  plot -> /tmp/an012/an012_image_pipeline.png
  PASS: YCbCr, edge map, histograms and latency gates met
```

The YCbCr frame equals the integer models bit for bit and sits 59 dB from the float matrix.

The edge map matches the model and agrees with the float reference on 97.4 % of the pixels; the
others lie on bar boundaries, where the hysteresis and the plain threshold decide differently.

The declared latency of branch B is 83 cycles on 32-pixel lines: 3 for the select matrix, 39 for the
Gaussian, 40 for the Sobel and 1 for the threshold.

Under backpressure the outputs stay identical and only the latency in cycles grows, so the latency
gate applies to the free-flowing pass only; the second frame reproduces the first.

![AN012 results (simulation). From left to right: the scene, the sensor mosaic, the demosaiced
and white-balanced image of the model, the gateware luma, the gateware edge map and the gateware
luma histogram.](img_an012_pipeline.png)

The example simplifies: bilinear demosaicing, 32-pixel lines and a constant white-balance error.

## Limits {#img-limits}

The blocks process one pixel per clock at a 100 MHz design target on ECP5 (1080p60 needs 148.5
MHz). Scaling is limited to box means by 2, 4 or 8, with no chroma subsampling and no frame
store.

Where to go next: [Image primer](#image-primer), [Using the application families](#apps-using),
[Image registers](#reg-image).
