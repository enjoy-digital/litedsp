# Images and video in a nutshell {#image-primer}

This chapter explains raster image processing to an FPGA engineer who has handled streams but
never a camera. It starts from the pixel and the frame, then covers colour sensors, point
operations, colour spaces, neighbourhood filters, geometry, statistics and composition, and ends
with video timing and frame buffers.

Each section gives the idea and the formula the blocks use, and ends with the LiteDSP block that
implements it. [Image and video blocks](#image) describes the blocks themselves. Fixed point,
rounding and saturation are in [Sampled signals and fixed point](#dsp-primer); streams and
framing in [Streams, latency and rates](#stream-primer).

## Pixels, lines and frames {#ipri-raster}

An image is a grid of *pixels*. A camera or a display moves through it in *raster* order: the
pixels of a line from left to right, then the lines from top to bottom. One full image is a
*frame*, and video is a sequence of frames. The figure below shows the scan order of a frame.

![Raster scan of a frame. The first pixel carries the start of frame, the last pixel of every
line the end of line, and the last pixel of the frame the end of frame.](ipri_raster.svg)

A pixel stream needs no coordinates as long as it marks the boundaries. Three tags are enough:
the first pixel of the frame, the last pixel of each line and the last pixel of the frame. A
consumer counts pixels from them to know the column and the row, and learns the width at the
first end of line.

In LiteDSP, pixel streams carry `first`, `eol` and `last` and no coordinates (`pixel_layout`);
`LiteDSPPixelCounter` derives the column, the row and the frame geometry from the tags.

## Pixel codes {#ipri-codes}

Each pixel holds one *code* per channel: an unsigned integer, 8 bits on most sensors and
displays, up to 16 bits on others. 0 is black and the largest code, *full scale*, is the
brightest value. A grey image has one channel; a colour image has three.

Arithmetic on codes needs signed intermediates and more bits than the codes themselves. The
result is then rounded back to the code width and *clamped* to the code range: a negative
result becomes 0, an overflow becomes full scale. Clamping is the image counterpart of
saturation ([Sampled signals and fixed point](#dsp-primer)).

Gains and colour coefficients are fixed-point numbers. LiteDSP uses unsigned Q4.8 gains (256
means 1.0), signed Q4.12 colour coefficients and a 9-bit blend factor (256 means 1.0).

## Colour sensors and demosaicing {#ipri-bayer}

A colour image sensor has one photosite per pixel and can measure only one colour at each. A
*colour filter array* in front of the sensor gives each photosite a red, green or blue filter.
The usual *Bayer* pattern repeats a 2 x 2 tile of one red, two green and one blue site, as the
figure below shows.

![A Bayer mosaic with the RGGB phase. Each photosite holds one code of one colour; demosaicing
interpolates the two missing colours of every pixel and emits one stream of RGB pixels, three
codes per pixel.](ipri_bayer.svg)

The raw sensor output is therefore a one-channel stream. *Demosaicing* rebuilds three channels
per pixel by interpolating the missing colours from the neighbours. Bilinear demosaicing takes
the mean of the nearest sites of each colour; it is cheap and leaves colour fringes on sharp
edges.

The tile can start on any of its four sites, so a sensor has a *phase*: RGGB, BGGR, GRBG or
GBRG. Cropping a sensor by an odd number of lines or columns changes the phase.

In LiteDSP, `LiteDSPDebayer` demosaics bilinearly with a build-time pattern and a runtime phase.

## Point operations {#ipri-point}

A *point operation* maps each pixel on its own, without looking at its neighbours. The common
ones are a gain and an offset per channel, a tone curve and a threshold.

A gain and an offset per channel give *white balance* (the sensor sees a white object with
unequal red, green and blue, and the gains equalize them), brightness and contrast. A simple
estimate of the white balance is *grey world*: it assumes the average scene is grey and sets the
gains so that the three channel means become equal.

A *tone curve* maps each code to another code through a table, a look-up table (LUT). *Gamma*
encoding `out = full (in / full)^(1/gamma)` is the usual one; any curve fits in the table.

A *threshold* turns a grey image into a binary one: full scale at or above the level, zero below.
With *hysteresis*, two levels and a memory along the line avoid flickering decisions on a noisy
edge: the output switches on above the high level and off below the low level.

In LiteDSP, the point operations are `LiteDSPPixelGain`, `LiteDSPPixelLUT` and
`LiteDSPThreshold`.

## Colour spaces {#ipri-colour}

RGB is what sensors and displays use. Compression and many algorithms prefer a *luma* channel,
the brightness Y, and two *chroma* channels, the colour differences Cb and Cr. The conversion is
a 3 x 3 matrix with offsets, computed per pixel.

The luma weights depend on the standard: `Y = 0.299 R + 0.587 G + 0.114 B` for BT.601,
`Y = 0.2126 R + 0.7152 G + 0.0722 B` for BT.709. *Studio range* video maps Y to 16..235 and the
chroma to 16..240 around 128. JPEG uses the *full range*, 0..255 for every channel.

A grey conversion is the luma row alone. Selecting one channel is a matrix row with a single 1.

In LiteDSP, `LiteDSPColorMatrix` applies any 3 x 3 or 1 x 3 matrix with offsets.

## Neighbourhood operations {#ipri-kernel}

A *neighbourhood operation* computes each output pixel from a small window around the input
pixel, typically 3 x 3 or 5 x 5. The most common is the *kernel*: each pixel of the window is
multiplied by a coefficient and the products are summed, then rescaled. The figure below shows
a 3 x 3 kernel.

![A 3 x 3 kernel operation. The window around pixel p is multiplied element by element with the
kernel (here the 3 x 3 Gaussian) and the sum, shifted right, is the output pixel.](ipri_window.svg)

The coefficients choose the effect, as the table below shows.

| Kernel | Coefficients | Effect |
|-----------|--------------------------------|----------------------------------------|
| Gaussian | 1 2 1 / 2 4 2 / 1 2 1, shift 4 | Smooths noise |
| Sharpen | 0 -1 0 / -1 5 -1 / 0 -1 0 | Enhances edges |
| Laplacian | 0 1 0 / 1 -4 1 / 0 1 0 | Second derivative, edges as zero crossings |
| Sobel x | -1 0 1 / -2 0 2 / -1 0 1 | Horizontal gradient |

The Laplacian and Sobel results are signed: their presets add half the full scale (128 for 8
bits), so that a zero response is mid-grey instead of being clamped to 0.

The *Sobel* operator computes the horizontal and vertical gradients `gx` and `gy` and combines
them into an edge strength: `|gx| + |gy|`, `max(|gx|, |gy|)`, or an approximation of the
Euclidean norm. The sign pattern also gives the edge direction.

A *rank filter* sorts the window and outputs one of its values. The middle value is the
*median*, which removes isolated noise pixels without blurring edges. The minimum is an
*erosion* and the maximum a *dilation*, the basic operations of binary morphology.

A window around a pixel needs the lines above it. A streaming implementation keeps the previous
`K - 1` lines in *line buffers*, so it holds `(K - 1) x width` pixels and delays the output by
about `K/2` lines. At the image borders, the missing neighbours are invented: repeat the edge
pixel, mirror the image, or use zero.

In LiteDSP, `LiteDSPLineBuffer` produces the windows; `LiteDSPKernel2D`, `LiteDSPSobel`,
`LiteDSPRankFilter` and `LiteDSPDebayer` are built on it.

## Geometry {#ipri-geometry}

*Downscaling* reduces the resolution. The box mean of each `D x D` tile is exact and cheap, and
it filters the image before dropping pixels, which avoids aliasing as decimation does on a
signal ([Streams, latency and rates](#stream-primer)). *Cropping* keeps a rectangular region of
interest and drops the rest.

Both change the number of pixels, so they are rate changers: fewer output pixels than input
pixels, with new frame tags.

In LiteDSP, these are `LiteDSPDownscaler` and `LiteDSPCrop`.

## Statistics and control loops {#ipri-stats}

A camera adjusts itself from statistics of the frames it captures. The *mean* of a channel, its
minimum and maximum, and the means of a few *zones* of the frame are enough for most loops. A
*histogram* counts how many pixels fall into each range of codes.

Three loops are common. *Auto exposure* compares the mean luma to a target and adjusts the
sensor exposure or a gain. *Auto white balance* computes the grey-world gains from the channel
means. *Histogram equalization* loads a tone curve built from the cumulative histogram, which
spreads the codes over the whole range.

The statistics are cheap in hardware; the loops are slow (once per frame) and run on the host
or a CPU.

In LiteDSP, `LiteDSPPixelStats` and `LiteDSPPixelHistogram` measure; the drivers of [Image and
video blocks](#image) run the loops.

## Composition {#ipri-blend}

*Alpha blending* mixes two images: `y = a A + (1 - a) B`, with `a` between 0 and 1, constant or
taken from a third image, the *mask*. An *overlay* draws on top of an image, for instance the
outlines of boxes around detected objects.

Both need two pixel streams in lock step: pixel k of one image meets pixel k of the other. When
one of the two went through a line buffer, it is late by about `K/2` lines, and the other branch
must be delayed by the same amount.

In LiteDSP, these are `LiteDSPAlphaBlend` and `LiteDSPBoxOverlay`; `LiteDSPPixelFIFO` delays a
branch.

## Video timing and frame buffers {#ipri-video}

A display needs pixels at a fixed *pixel clock*, with *blanking* intervals between lines and between
frames. The *video timing* gives, for each clock, the horizontal and vertical sync pulses and a
*data enable* (`de`) that is high on active pixels.

A pixel stream with ready and valid has no blanking; adapting it to a display means pausing it
during the blanking and filling with black when it is late.

A *frame buffer* stores frames in memory. The pixels are packed into memory words: 24-bit RGB,
32-bit XRGB with a padding byte, 16-bit RGB565 with 5, 6 and 5 bits, or one byte per grey pixel.

In LiteDSP, `LiteDSPPixelFromVideo` and `LiteDSPPixelToVideo` adapt the LiteX video streams;
`LiteDSPPixelPack` and `LiteDSPPixelUnpack` convert pixels to and from memory words.

## Where to go next {#ipri-next}

The blocks, their streams and their host helpers are in [Image and video blocks](#image); the
motor blocks start with [Motor control blocks](#motor).
