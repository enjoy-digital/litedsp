```{=latex}
\mainmatter
\part{Understand}
```

```{=html}
<h1 class="part">Part I. Understand</h1>
```

# Introduction {#introduction}

This chapter says what LiteDSP is, what it does and what it does not do, and how far each family
of blocks has been taken on the way to hardware. It ends with the layout of the repository and a
map of the manual. Every reader should start here.

## What the project is {#intro-what}

LiteDSP is a library of signal processing blocks for FPGAs. Each block is a piece of gateware
written in Python with Migen and LiteX: an oscillator, a mixer, a filter, a rate changer, an FFT,
a demodulator, a decoder.

The blocks are pure HDL, with no vendor IP, so the same design simulates end to end and builds on
any FPGA that LiteX supports.

All the blocks share one contract. Samples travel on LiteX streams with full flow control,
every block states its latency in samples, and every block is controlled the same way, from
registers or from plain signals. Blocks therefore connect to each other with one `connect()`
call, in a LiteX SoC or in a netlist that the tools turn into Verilog. [Block
contract](#architecture) describes the contract.

The figure below shows a typical receive design. Converter samples enter through a frontend
block, a chain of blocks processes them, and the result reaches the host through a capture
buffer, a DMA engine or a UDP link. The host tunes the blocks through their registers.

![A LiteDSP design: the frontend adapts the converter samples, a chain of blocks processes them,
and the result leaves through a capture, DMA or UDP block. Follow the cyan path: the samples;
the thin lines are the register accesses of the host.](intro_overview.svg)

Every block has unit tests under random flow control; most are compared bit for bit with a
golden model, a NumPy description of the same arithmetic in `test/models.py`. Many are also
co-simulated in Verilator and built with Yosys, nextpnr and Vivado; [Status](#intro-status) says
which.

## Features at a glance {#intro-features}

| Area | Features |
|-------------------|---------------------------------------------------------------------------------|
| Portability | Pure Migen and LiteX, no vendor primitive or IP; simulates end to end; Verilog output for any FPGA tool |
| Fixed point | Signed Qm.n samples, Q1.15 by default; shared rounding and saturation helpers at every narrowing point |
| Blocks | 229 blocks in 13 families: RF and signal processing, communications, stream utilities, and four application families (motor, audio, radar, image) |
| Throughput | One sample per clock by default; parallel variants carry several samples per clock |
| Tools | Netlist flow to Verilog and AXI IP, standalone core generator, node editor GUI with live tuning, host drivers and a CLI |
| Verification | Golden models, random backpressure, Verilator lint and co-simulation, formal proofs of the stream plumbing, characterization and implementation budgets in CI |
| Documentation | One generated datasheet per block (`doc/blocks/`), application notes with simulation plots, this manual |

## Families at a glance {#intro-families}

The registry, the list of all blocks used by the tools, groups the blocks in families. The table
below gives the number of blocks of each family and a few of them; the
[block catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md) has
one datasheet per block.

| Family | Blocks | Examples | Chapter |
|----------------|-----------|--------------------------------|-----------------------------------------|
| generation | 6 | NCO, CORDIC, chirp, noise source, replay, patterns | [Generation and mixing](#generation-mixing) |
| mixing | 5 | Mixer, DDC, DUC, channelizer, polyphase filter bank | [Generation and mixing](#generation-mixing) |
| correction | 3 | DC offset, I/Q balance, derotator | [Generation and mixing](#generation-mixing) |
| filter | 22 | FIR, polyphase, CIC, half-band, IIR, Farrow, LMS equalizer | [Filters and rate change](#filters-rate) |
| rate | 5 | Decimator, interpolator, naive down and up samplers | [Filters and rate change](#filters-rate) |
| level | 13 | Gain, power, AGC, squelch, CFR, DPD actuator, dB | [Level control and analysis](#level-analysis) |
| analysis | 14 | Window, FFT, PSD, Welch, Goertzel, histogram, error counter | [Level control and analysis](#level-analysis) |
| comm | 51 | Demodulators, carrier and timing recovery, Viterbi, Reed-Solomon, LDPC, OFDM | [Communications blocks](#comm) |
| stream | 23 | Split, combine, delay, FIFO, capture, framer, timestamps | [Stream utilities and host links](#stream-frontend) |
| motor | 19 | Clarke and Park, PI loops, SVPWM, PWM, encoders, FOC | [Motor control](#motor) |
| audio | 19 | I2S, PDM, equalizer, compressor, dither, loudness | [Audio](#audio) |
| radar | 17 | Pulse compression, MTI, Doppler, CFAR, trackers | [Radar and sonar](#radar) |
| image | 32 | Line buffer, 2-D kernels, debayer, colour matrix, statistics | [Image and video](#image) |

Some classes are not registry blocks: the frontend (ADC and DAC interfaces, I/Q packetizer, UDP
I/Q streamer), the DMA capture and replay, the time core, and most parallel variants. They follow
the same contract and have their own tests.

## Status {#intro-status}

No run of LiteDSP on a board is recorded in the repository. What is recorded is simulation,
synthesis, place and route, and bench bitstreams. The table below gives, per family, how many
registry blocks reach each step; the words used in the last column are defined under it.

| Family | Blocks | Co-sim | ECP5 synth, P&R | Artix-7, AU+ P&R | Status |
|-----------------|------------|------------|-------------|---------------|-------------------------------|
| generation | 6 | 2 | 4, 4 | 2, 2 | Implemented; NCO and noise source built for a board |
| mixing | 5 | 2 | 5, 5 | 4, 4 | Implemented; DDC built for a board |
| correction | 3 | 1 | 0, 0 | 0, 0 | Simulated |
| filter | 22 | 12 | 11, 9 | 5, 6 | Implemented |
| rate | 5 | 2 | 1, 1 | 1, 1 | Implemented |
| level | 13 | 7 | 8, 7 | 2, 2 | Implemented |
| analysis | 14 | 6 | 11, 10 | 2, 3 | Implemented |
| comm | 51 | 41 | 36, 19 | 8, 8 | Implemented |
| stream | 23 | 5 | 10, 7 | 0, 0 | Implemented; capture built for a board |
| frontend | n/a | n/a | n/a | n/a | Simulated; UDP I/Q streamer built for a board |
| motor | 19 | 15 | 19, 0 | 0, 0 | Synthesized |
| audio | 19 | 10 | 18, 0 | 0, 0 | Synthesized |
| radar | 17 | 17 | 17, 0 | 0, 0 | Synthesized |
| image | 32 | 27 | 22, 0 | 0, 0 | Synthesized |

The counts are registry keys with an exact entry in `sim/cosim_specs.py` (co-simulation) and in
`impl/budgets.json`: on ECP5, synthesis then place and route (P&R); on Artix-7 and Artix
UltraScale+ (AU+), place and route. A block with a place and route entry counts as synthesized
(the two CCSDS Reed-Solomon blocks have only a place and route entry).

Variants recorded under other keys, such as `fir_parallel_x2` or `viterbi_decoder_soft`, are not
counted, so the counts are lower bounds. The parallel variants of the NCO, mixer, CIC decimator,
FFT and DDC have their own place and route entries on ECP5. The I/Q adder (`LiteDSPIQAdd`) and
the register reader of the spectrum bench are built for a board too but are not registry blocks.

A family row gives the furthest step that some of its blocks reach; the counts say how many.
The status words mean:

- **Simulated**: the block has unit tests in CI under random backpressure, against its golden
  model where it has one (170 of the 229 registry blocks) or against values computed in the
  test; every registry block is exercised by the tests. The Co-sim column counts
  the blocks also run as Verilog in Verilator against their golden model.
- **Synthesized**: a synthesis result is recorded in `impl/budgets.json` for the device (ECP5
  `LFE5UM5G-85F` with Yosys), with no place and route. The four application families are at
  this step.
- **Implemented**: a place and route result is recorded for the device (ECP5 with nextpnr,
  Artix-7 `xc7a200t` and Artix UltraScale+ `xcau20p` with Vivado), with the raw fmax and the gate
  floor checked by CI. These are out-of-context tool results with default parameters.
- **Built for a board**: the block is part of a bench design whose bitstream was built through
  place and route for a board: the spectrum bench on the Colorlight 5A-75B (60 MHz) and the
  UDP stream bench on the same board (40 MHz). [Boards and benches](#boards) describes them.

Characterization numbers quoted in this manual, such as an SFDR or a filter ripple, are
measured on the golden models. Resource and fmax numbers are out-of-context tool results from
`impl/budgets.json`; [Performance and resources](#performance) tables them.

## Known issues {#intro-known-issues}

The table lists the known defects of the default branch: what the code does today and how to
work around it. The chapters describe the same behaviour where the block is documented.

| Block or tool | Behaviour on the default branch | Workaround, details |
|----------------------|------------------------------------------------|------------------------------------------|
| DDC docstrings | Say to set `phase_inc` to `-f_tune`; the down mixer brings `+f_tune` to DC; fix pending (PR #13) | Use `+f_tune`; [DDC](#gm-ddc) |
| Bench scripts | `test_spectrum.py` and `test_stream.py` tune the DDC to `-tune`: the tone lands at tone + tune and the check fails with the defaults; fix pending (PR #13) | Tune to `+tune`; [Spectrum bench](#brd-spectrum) |
| PWM | Docstring and `PWMDriver.set_trigger` default sample at the valley; low-side shunts conduct at the peak. A fault drops the gates two clocks later, not one, as the docstring says; fix pending (PR #16) | Trigger at `period`, direction 1; [PWM](#mot-pwm), [Protection](#mot-protection) |
| Complex FIR | Bypassed, connects input to output with no latency: switching `bypass` under traffic can reorder beats; fix pending (PR #10) | Switch `bypass` while the stream is idle; [FIR filters](#fr-fir) |
| RMS meter | A result is lost when the consumer stalls past the next window or the window is short | Keep the consumer ready; [Power, RMS](#lvl-measure) |
| Capture | Read only through the Wishbone window, it stays in readout and ignores the next trigger | Drain its `source` or reset it; [Capture](#str-capture) |
| Wishbone DMA capture | Ends a non-looping transfer at the `last` of a framed stream | Strip the framing or use `loop`; [DMA](#str-dma) |
| DDC chain example | In `examples/ddc_chain.py` the rejected tone folds onto DC, so the printed rejection is the division floor | Read the in-band result only; [First chain](#gs-chain) |

## What it is not {#intro-limits}

LiteDSP is a library of gateware blocks and the tools around them. It is not:

- a wrapper of vendor DSP IP: no block instantiates a vendor primitive, and the tools infer
  multipliers and memories from plain HDL;
- a floating-point library: every datapath is fixed point, with explicit widths, rounding and
  saturation;
- a host signal processing library: the host software configures blocks, drains captures and
  fits a few tables, such as the predistortion lookup tables (`litedsp/software/dpd.py`); it does
  not process the sample streams;
- a frozen API: the project is a work in progress, and block interfaces, parameter names and the
  repository layout can change before the first stable release.

The application families are also less mature than the RF families on recorded evidence: they
are synthesized on ECP5 only, as [Status](#intro-status) shows.

## Tools {#intro-tools}

Everything the tools know about a block comes from the registry. Each tool builds the block once
with its registers, reads back its ports, registers, latency and documentation, and uses that
description, as the figure below shows.

![The registry feeds every tool: the datasheet generator, the flow and the generator that write
Verilog, the GUI, and the host drivers.](intro_tools.svg)

The flow (`litedsp_flow`) turns a JSON netlist into Verilog, a register map and an AXI IP. The
generator (`litedsp_gen`) turns a YAML file into a standalone core. The GUI (`litedsp_gui`) edits
netlists and tunes a running SoC. The host drivers and `litedsp_cli` talk to the blocks over
`litex_server`, and the datasheet generator writes `doc/blocks/`.

The verification tools are scripts of the repository: the unit tests (`test/`), the Verilator
lint and co-simulation (`sim/`), the synthesis and place and route sweeps (`impl/`), the
characterization (`char/`) and the formal proofs (`formal/`).
[Flow, generator, GUI and host software](#tooling) and [Verification](#verification) describe
them.

## Repository layout {#intro-layout}

| Path | Content |
|-----------------------------------|-----------------------------------------------------------------|
| `litedsp/` | The blocks, one directory per family, plus `common.py` (layouts, fixed-point helpers, bypass) |
| `litedsp/frontend/` | Converter interfaces, I/Q packetizer, UDP I/Q streamer |
| `litedsp/flow/` | Registry, block reflection, netlist, chain builder, IP packaging, datasheet generator |
| `litedsp/gui/`, `litedsp/software/` | Node editor GUI; host drivers and CLI |
| `test/` | Unit tests and the NumPy golden models (`test/models.py`) |
| `sim/` | Verilator lint and co-simulation of the registry blocks |
| `impl/`, `char/`, `formal/` | Implementation sweeps and budgets, characterization, formal proofs |
| `examples/` | Example chains and application notes scripts, generator YAML files |
| `bench/` | Bench designs for the Arty and the Colorlight 5A-75B, with their host scripts |
| `tools/` | Coding style checker |
| `doc/` | Block datasheets (`doc/blocks/`), application notes (`doc/app_notes/`), this manual (`doc/manual/`) and its figures (`doc/diagrams/`) |

## License and credits {#intro-license}

LiteDSP is released under the BSD 2-Clause license by Enjoy-Digital. It can be used in
closed-source designs. It is written in Migen and LiteX and is part of the LiteX ecosystem of
cores.

The authors are listed in the `CONTRIBUTORS` file and in the history of the repository; each
source file names its main authors in its header.

## How to read this manual {#intro-reading}

The manual has four parts. Part I explains the signal processing behind the blocks: sampled
signals and fixed point, streams and rates, filters, oscillators and the FFT, and digital
communications. Part II describes the core: the block contract, then each group of families.

Part III is the user guide: installation, integration, examples, benches, verification and
debugging. Part IV covers the application families, motor control, audio, radar and image, each
with its own primer.

If fixed point or streams are new to you, read [Sampled signals and fixed point](#dsp-primer)
next. Otherwise, the table below sends each question to its chapter.

| Question | Chapter |
|--------------------------------|--------------------------------------------------------------------|
| How are samples and fixed point handled? | [Sampled signals and fixed point](#dsp-primer) |
| How do streams, latency and rate changes work? | [Streams, latency and rates](#stream-primer) |
| What does every block have in common? | [Block contract](#architecture) |
| Which block tunes, mixes or filters? | [Generation and mixing](#generation-mixing), [Filters and rate change](#filters-rate) |
| How do I measure a signal or its spectrum? | [Level control and analysis](#level-analysis) |
| Which modem and FEC blocks exist? | [Communications blocks](#comm) |
| How do samples reach the host? | [Stream utilities and host links](#stream-frontend) |
| How do I generate Verilog or an IP core? | [Flow, generator, GUI and host software](#tooling) |
| How do I run a first chain? | [Getting started](#getting-started) |
| How do I add blocks to my SoC? | [Integration](#integration) |
| What do the examples do? | [Examples](#examples) |
| How is a block verified? | [Verification](#verification) |
| My chain stalls or the output is wrong: what now? | [Debugging](#debugging) |
| What about motor, audio, radar or image? | [Application families](#apps-introduction) |
| Which registers does a block have? | [Registers](#registers) |
