```{=latex}
\part{Application families}
```

```{=html}
<h1 class="part">Part IV. Application families</h1>
```

# Application families {#apps-introduction}

This part covers the four families of LiteDSP blocks that serve a product domain rather than a
radio: motor control, audio, radar and sonar, and image processing. It is for an engineer who
builds a drive, an audio device, a sensor front end or a camera pipeline on an FPGA. The part has
one primer per domain, then one chapter per family, then one chapter on using them; a reader who
knows the domain can skip its primer. The application notes of these families run on the golden
models and in Migen simulation, not on a board.

The families reuse everything Parts I to III describe. This chapter states what they share and
what each one adds.

## At a glance {#apps-glance}

| Family | Directory | Blocks | Chapters | Notes |
|--------------|---------------------------|----------|-------------------------------------|------------|
| Motor control | `litedsp/motor/` | 19 | [Primer](#motor-primer), [blocks](#motor) | AN009 |
| Audio | `litedsp/audio/` | 19 | [Primer](#audio-primer), [blocks](#audio) | AN010 |
| Radar and sonar | `litedsp/radar/` | 17 | [Primer](#radar-primer), [blocks](#radar) | AN004, AN011 |
| Image and video | `litedsp/image/` | 32 | [Primer](#image-primer), [blocks](#image) | AN012 |

The block counts are the registry entries of each category in `litedsp/flow/registry.py`. Some
entries are presets of one class: in image, 11 of the 32 entries are kernel, rank, LUT,
colour-matrix and blend presets of 21 classes ([Audio blocks](#audio) lists the audio presets).
The development status of each family is in the [status table](#intro-status) of the
introduction.

The figure below places the four families on the shared base: the block contract, the registry
and the tools that read it.

![The four application families on the shared LiteDSP base. Every family block follows the same
stream contract and is listed in the same registry, which the tools, the datasheets and the tests
read.](apps_families.svg)

## What the families share {#apps-shared}

Every block of these families is a `LiteDSP`-prefixed Migen module with full `valid`/`ready`
backpressure on its streams and a declared `latency`, `None` when it buffers a frame or has a
stream on one side only: the [Block contract](#architecture), the control and register rules
([Register reference](#registers)) and the fixed-point rules of [Sampled
signals and fixed point](#dsp-primer) apply unchanged. The families only change the default
formats: Q1.15 per-unit currents for motors, Q1.23 samples for audio, unsigned 8-bit codes for
pixels. The tools of [Flow, generator, GUI and host software](#tooling) build chains of them, and
each processing block has a bit-exact NumPy golden model tested under randomized backpressure
([Verification](#verification)); the video adapters, the pixel FIFO and the packers are tested
without one.

## What each family adds {#apps-adds}

Each family adds payload layouts to `litedsp/common.py` and a convention for the meaning of their
fields: three-phase and angle samples for motors (`abc_layout`, `angle_layout`), channel-tagged
TDM beats for audio (`tdm_layout`), bursts of cells, targets and tracks for radar
(`cell_layout`, `target_layout`, `track_layout`), and raster pixels framed by `first`, `eol` and
`last` for images (`pixel_layout`, `window_layout`, `video_layout`). The family chapters explain
them.

Each family also has pin-level blocks with no stream on one side. The motor PWM drives six gate
signals, the encoder decoders read sensor pins, and the I2S and PDM converters drive and sample
serial audio lines. These blocks sit next to a stream chain rather than inside it, which shapes
the standalone cores of [Using the application families](#apps-using).

Finally, each family has host-side design math: per-unit gains for motors, biquad designs and time
constants for audio (`litedsp/audio/design.py`), waveform and detector settings for radar
(`litedsp/radar/design.py`), kernels and colour matrices for images (`litedsp/image/design.py`).
The drivers call this math, so the host writes hertz, decibels and milliseconds rather than
register words.

Where to go next: [Motor control primer](#motor-primer), or [Using the application
families](#apps-using) for the generators and the drivers.
