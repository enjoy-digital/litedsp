```{=latex}
\part{The core}
```

```{=html}
<h1 class="part">Part II. The core</h1>
```

# Block contract {#architecture}

This chapter describes what every LiteDSP block has in common: its streams, its flow control, its
latency, its control signals and registers, its bypass, its reset and interrupts, its parameters,
and how the registry describes it to the tools.

Read it before using a block, and again before writing one. The concepts behind it, fixed point,
flow control and rate changes, are explained in [Sampled signals and fixed point](#dsp-primer) and
[Streams, latency and rates](#stream-primer).

## At a glance {#arch-glance}

| Item | Convention |
|----------------|------------------------------------------------------------------------------------|
| Class | `LiteXModule` with a `LiteDSP` prefix, most wrapped with `@ResetInserter()` |
| Streams | LiteX `stream.Endpoint`: `sink` in, `source` out; `sink_a`/`sink_b` or `sinks` for several inputs |
| Payload layouts | Functions of `litedsp/common.py`: `iq_layout`, `real_layout` and the family layouts |
| Flow control | Full `valid`/`ready` backpressure, no sample dropped or duplicated (documented exceptions) |
| Latency | `self.latency` in samples, or `None` when data dependent |
| Control | Plain control signals, wired to registers by `add_csr()` when `with_csr=True` |
| Bypass | Boolean `bypass` on 48 in-line blocks, delay-matched by `add_bypass()` |
| Interrupts | `with_irq=True` adds a LiteX `EventManager` on trigger-type blocks |
| Fixed point | Signed Qm.n, Q1.15 by default; round and saturate at every narrowing point |
| Parameters | Defaults (or registry values), a shared vocabulary, `check()` raises `ValueError` |
| Description | The registry reflects each block into a `BlockSpec` used by every tool |

## Anatomy of a block {#arch-anatomy}

A block takes samples on its `sink` endpoint, processes them in a pipelined datapath and presents
the result on its `source` endpoint. The datapath never reads a register directly: it reads plain
control signals, which a register bank or a parent module drives.

The figure below shows the parts of a typical in-line block, such as the gain. The bypass path
runs next to the datapath with the same number of stages, and a multiplexer picks one of the two
at the output.

![Anatomy of a block: samples enter on the sink and leave on the source after the datapath; the
registers added by add_csr() drive plain control signals; the bypass delay has the latency of the
datapath and the bypass select travels with its beat through it.](arch_block.svg)

The code of a block follows the same order. The constructor declares the endpoints, the control
signals and `self.latency`, then a `# # #` separator, then the hardware, and calls `add_csr()` at
the end when `with_csr` is set. The gain block, `litedsp/level/gain.py`, is a short example to
read.

## Streams and layouts {#arch-streams}

Blocks exchange samples on LiteX streams. A block with one input and one output has a `sink` and
a `source`. A block with two inputs, such as the mixer, names them `sink_a` and `sink_b`; a block
with a variable number of inputs, such as the combiner, has a `sinks` list.

The payload layouts come from `litedsp/common.py`, so two blocks that carry the same kind of data
use the same field names. The table below lists them.

| Function | Fields | Used for |
|-------------------------------|--------------------------|-------------------------------------------|
| `real_layout` | `data` (signed) | Real samples |
| `iq_layout` | `i`, `q` (signed) | Complex baseband samples, the default |
| `iq_symbol_layout` | `i`, `q`, `symbol` | A sample with its hard decision (QPSK) |
| `abc_layout` | `a`, `b`, `c` (signed) | Three-phase quantities (motor) |
| `angle_layout` | `angle` (signed) | Electrical angle, a full turn is `2**angle_width` |
| `tdm_layout` | `data`, `channel` | Channel-tagged audio, one channel per beat |
| `cell_layout` | `data`, `threshold`, `detect` | Radar detector cells |
| `target_layout` | `range`, `doppler`, `data`, `hit` | Radar detections, one burst per interval |
| `track_layout` | `range`, `doppler`, `velocity`, `id`, `hits`, `hit` | Radar tracks |
| `pixel_layout` | `data` or `r`, `g`, `b`, plus `eol` | Image pixels |
| `window_layout` | `w00` to `w22` (3 x 3) or up to `w66` (7 x 7), `eol` | K x K pixel neighbourhoods |
| `video_layout` | `hsync`, `vsync`, `de`, `r`, `g`, `b` | Timed video, compatible with LiteX video |
| `time_param_layout` | `timestamp`, `stream_id` | Stream parameters of timestamped streams |

Two-phase motor vectors (alpha and beta, d and q) ride on `iq_layout`, so the Park rotation is the
complex mixer. The audio, radar and image layouts and their framing rules are described with
their families in Part IV.

A time-shared engine that serves several channels, such as the resampler farm, takes one stream
per channel and emits one channel-tagged stream: `iq_layout` plus a `channel` field. A
`LiteDSPChannelDemux` whose `sel` input follows the tag fans it back out, as
[Routing and fan-out](#str-routing) shows.

## Flow control {#arch-flow}

Every block honours the full `valid`/`ready` handshake, with the few documented exceptions listed
with their block (the RMS meter, see [Level control and analysis](#level-analysis)).
[Backpressure](#pri-backpressure) and [Elastic pipelines](#pri-elastic) explain the rules; this
section shows how the code applies them. Most blocks advance their pipeline with one signal, as
the gain block does:

```python
adv = Signal()
self.comb += [
    adv.eq(self.source.ready | ~self.source.valid),
    self.sink.ready.eq(adv),
]
```

A block with a history, such as a FIR filter, advances it only on `sink.valid & sink.ready` and
drains its arithmetic on every free output slot; `litedsp/filter/fir.py` is the reference. A
per-beat control, such as `bypass`, travels with its beat through the pipeline.

`LiteDSPSplit` raises the `valid` of its outputs from its input alone, never from a `ready`, so
its branches may rejoin at one block, such as both inputs of the mixer, without a loop between
the handshakes ([Routing and fan-out](#str-routing)).

## Latency {#arch-latency}

Each block states its pipeline depth in `self.latency`, counted in samples at its own beat, or
`None` when it depends on the data ([Latency in samples](#pri-latency)). A composite gives the
sum of the latencies of its stages: the DDC, for example, adds the 2 cycles of its mixer to the
latency of its decimator ([Generation and mixing](#generation-mixing)).

The flow balances reconvergent paths from these values, the timestamp recipe adds them
([Timestamps](#str-timestamps)) and `add_bypass()` delays its path by them. The latency is the
pipeline delay of a sample; a block that also delays the content of its signal, such as a FIR by
its group delay or the CFR by its delay line, publishes that delay apart (the CFR as `delay`), and
the flow does not balance it.

`test/test_metadata_policy.py` fails when a block with an input and an output has no latency,
unless its key is in the `VARIABLE_LATENCY` list, and then checks that it is `None`.
`test/test_latency.py` measures the declared values, including those of the Viterbi decoder, the
iterative FFT and the DDC, DUC and channelizer composites.

## Control {#arch-control}

The datapath of a block reads plain control signals: `self.gain`, `self.phase_inc`,
`self.bypass`. The constructor argument `with_csr` decides who drives them, as the figure below
shows.

![The two control modes: with with_csr=True, add_csr() creates registers on the CSR bus and wires
them to the control signals; with with_csr=False, a parent module or a test drives the signals
directly.](arch_control.svg)

With `with_csr=True`, the default, the constructor calls `add_csr()`. This method declares the
registers, `CSRStorage` for settings and `CSRStatus` for status, with named and documented
fields, and wires them to the control signals. The gain block does it in a few lines.

```python
def add_csr(self):
    self._gain   = CSRStorage(self.data_width, reset=(1 << self.gain_frac), name="gain",
        description="Gain mantissa (signed Q2.(N-2), 1.0 = 2**(N-2)).")
    self._control = CSRStorage(fields=[
        CSRField("shift",     size=2, offset=0, description="Extra right shift (/1, /2, /4, /8)."),
        CSRField("bypass",    size=1, offset=2, description="Bypass gain (passthrough)."),
        CSRField("clear_sat", size=1, offset=3, pulse=True, description="Clear saturation flag."),
    ])
    self._status = CSRStatus(fields=[
        CSRField("saturation", size=1, description="Output saturated since last clear."),
    ])
    self.comb += [
        self.gain.eq(     self._gain.storage),
        self.shift.eq(    self._control.fields.shift),
        self.bypass.eq(   self._control.fields.bypass),
        self.clear_sat.eq(self._control.fields.clear_sat),
        self._status.fields.saturation.eq(self.sat),
    ]
```

With `with_csr=False`, the block has no register and its parent drives the signals. Composites
build some of their sub-blocks this way: the DDC builds its mixer with `with_csr=False` and drives
its mode itself, while its NCO keeps its own registers.

Tests use it too, often by setting the reset value of a control signal (`dut.bypass.reset = 1`) so
that the value is stable from the first cycle.

The registers of every registry block are listed in [Registers](#registers). In a LiteX SoC,
their names take the prefix of the instance, such as `ddc_nco_phase_inc`.

## Bypass {#arch-bypass}

48 registry blocks expose a boolean `bypass` ([Bypass](#pri-bypass) explains the behaviour). Most
get it from `add_bypass()` of `litedsp/common.py`, called at the end of the hardware section, and
its register from `add_bypass_csr()`, called from `add_csr()`. `add_bypass()` delays a copy of
the input and the select through as many stages as the latency of the block and muxes it onto the
output, so a toggle lands on an exact beat boundary.

The DC blocker, the moving average, the comb filter, the IIR biquad and the DC offset canceller
differ: they have the `bypass` signal but no bypass register, even with `with_csr=True`. The
complex FIR filter drives the `bypass` of its two real filters, so it keeps their delay matching.

`test/test_bypass.py` checks, under random stalls, that each listed block is an exact passthrough
when bypassed, and switches the complex FIR under traffic. The mixer's `bypass` is 2 bits wide and
selects which input passes instead of the product.

## Reset and interrupts {#arch-reset-irq}

Most blocks are wrapped with `@ResetInserter()`, which adds a `reset` input that clears the block
without touching the rest of the design. Some blocks have none, among them the pure stream
plumbing, the composites built from other blocks and a few wrappers; check for a `reset`
attribute before relying on it.

Trigger-type blocks can raise interrupts instead of being polled. With `with_irq=True`, or by
calling `add_irq()`, they add a LiteX `EventManager` (`self.ev`) with edge-triggered event sources
on their status signals.

About twenty blocks offer it, among them the squelch, the energy detector, the capture, the AGC,
the frame synchronizer and the time core. A SoC routes the event manager to its CPU with
`soc.irq.add("<name>")`.

## Fixed point {#arch-fixed-point}

Samples are signed Q1.15 by default. Every narrowing point goes through `rounded()`,
`saturated()` or `scaled()` of `litedsp/common.py` ([Fixed point in LiteDSP](#pri-fixed-point)
lists the helpers). Each helper has a NumPy twin in `test/common.py` with the same arithmetic,
which keeps the golden models bit identical to the gateware.

## Parameters {#arch-params}

Every constructor parameter has a default, or a value in the registry entry, so the tools can
build any block. Parameter names follow one vocabulary across the blocks:

| Name | Meaning | Not |
|------------------------------------|-----------------------------------------------|-----------------|
| `decimation`, `interpolation` | Integer rate factors | `R`, `L`, `factor`, `ratio_int` |
| `n_stages`, `diff_delay` | CIC stages and differential delay | `M` |
| `n_taps`, `coefficients` | FIR length and coefficient list | `taps`, `coeffs` |
| `sections` | Second-order sections of an IIR | |
| `polynomial` | LFSR taps of a scrambler or a CRC | |
| `N` | Transform size (FFT, PSD, Goertzel, window) only | |
| `data_width` | Sample width in bits | |
| `n_samples` | Samples per beat of a parallel variant | |

`test/test_metadata_policy.py` rejects the names of the Not column; `N` is a convention, not
checked. Invalid parameters raise a `ValueError` from `check(condition, message)` of
`litedsp/common.py`, not an `assert`. The check therefore survives `python -O`, and the message says
what is expected, such as `expected n_samples >= 1`.

## Parallel variants {#arch-parallel}

Parallel variants carry `n_samples` samples per beat for converters faster than the clock
([Sample rate, clock rate and lanes](#pri-rates)). The lanes of a beat are packed in each field,
lane 0, the oldest sample, in the least significant bits. A variant is bit identical to its serial
counterpart: the flattened sequence of lanes is the serial output.

The figure below shows a parallel front end. The parallel DDC mixes four samples per clock and
decimates by a multiple of four, so its output is an ordinary stream of one sample per beat that
the serial blocks take directly. Where a parallel block does not decimate, such as the parallel
FIR, `LiteDSPIQParallelToSerial` returns to one sample per beat.

![A parallel front end: the parallel DDC takes four lanes per beat and outputs one sample per
beat; a parallel FIR keeps four lanes and LiteDSPIQParallelToSerial serializes them. Lane 0 sits
in the least significant bits of each field.](arch_parallel.svg)

| Class | File (under `litedsp/`) |
|---------------------------------------------------|-------------------------------------------------|
| `LiteDSPParallelNCO` | `generation/nco_parallel.py` |
| `LiteDSPParallelMixer` | `mixing/mixer_parallel.py` |
| `LiteDSPParallelDDC` | `mixing/ddc_parallel.py` |
| `LiteDSPParallelFIRFilter`, `LiteDSPParallelFIRFilterComplex` | `filter/fir_parallel.py` |
| `LiteDSPParallelCICDecimator` | `filter/cic_parallel.py` |
| `LiteDSPParallelFFT` | `analysis/fft_parallel.py` |
| `LiteDSPIQSerialToParallel`, `LiteDSPIQParallelToSerial` | `stream/adapt.py` |

`real_lanes()` and `iq_lanes()` of `litedsp/common.py` return the bit slices of the lanes. Only
the parallel FFT is a registry block; the others are used directly in Python.
`LiteDSPLDPCDecoderZParallel` is parallel inside only: it processes several lanes of the code at
once but keeps one LLR per beat ([Communications blocks](#comm)).

## The registry {#arch-registry}

The registry, `litedsp/flow/registry.py`, is the list of the blocks that the tools know. Each
entry of its `ENTRIES` list gives a key, a class, construction arguments, a family, a display
name and the choices of the enumerated parameters:

```python
("gain", LiteDSPGain, {}, "level", "Gain", None),
```

`registry()` reflects every entry once and caches the result. The reflection,
`reflect()` of `litedsp/flow/metadata.py`, builds the block with `with_csr=True` and reads back
what the block declares. It never parses the source. The result is a `BlockSpec`:

| Field | Content |
|-----------------------------------|-----------------------------------------------------------------|
| `key`, `category`, `display_name` | Registry key, family and name shown by the GUI |
| `params` | Constructor parameters with defaults, kinds, choices and descriptions |
| `ports` | Every stream endpoint, with its direction and layout kind |
| `csrs` | Every register, with its access, reset and fields (from `get_csrs()`) |
| `latency` | The `latency` attribute of the built block |
| `doc`, `doc_full` | First line and full text of the class docstring |
| `has_csr`, `has_bypass` | Whether the class takes `with_csr` and exposes `bypass` |

Every tool works from these specs: the datasheet generator, the flow and its delay balancer, the
standalone generator, the GUI palette, the register appendix of this manual and the auto-discovery
of the host drivers.

Because the specs come from the built block, the datasheets cannot drift from the code; CI runs
`python3 -m litedsp.flow.docgen --check` to make sure the committed ones are up to date.

## Adding a block {#arch-new-block}

A new block follows the contract above. The checklist of `CONTRIBUTING.md` sums it up:

1. A BSD-2-Clause header; imports grouped as Migen, then `litex.gen`, then registers and streams,
   then `litedsp`.
2. A `LiteXModule` with `@ResetInserter()` and a `LiteDSP` prefix, or a
   `stream.PipelinedActor` for a stateless map. Helpers that are not hardware, such as `Qmn`,
   drivers and functions, take no prefix.
3. The endpoints with layouts from `litedsp/common.py`, the control signals and `self.latency`,
   then the `# # #` separator, then the hardware. The class is re-exported from the
   `__init__.py` of its family.
4. Parameters from the shared vocabulary, all with defaults, checked with `check()`. A block
   that keeps its layout adds `add_bypass()` and `add_bypass_csr()`.
5. Full backpressure, with an elastic pipeline when the block has state.
6. Rounding and saturation at every narrowing point, with the helpers of `litedsp/common.py`.
7. `if with_csr: self.add_csr()` at the end, with named and documented register fields, and
   `with_irq` with `add_irq()` for a trigger-type block.
8. A NumPy golden model in `test/models.py` and a test in `test/test_<block>.py`: bit exact where
   the arithmetic is deterministic, against an SNR threshold where rounding differs, always under
   random backpressure.
9. An entry in `litedsp/flow/registry.py` to make the block available to the tools, and a driver
   in `litedsp/software/drivers.py` if the host tunes it at run time.

[Verifying a new block](#ver-new-block) gives the verification rows a block joins and
[Verification](#verification) the commands that CI runs.

## In the code {#arch-code}

| File | Content |
|-----------------------------------------------|-----------------------------------------------------|
| `litedsp/common.py` | Layouts, lanes, `check()`, fixed-point helpers, `add_bypass()` |
| `litedsp/control.py` | `LiteDSPPILoop`, the loop filter shared by the tracking loops |
| `litedsp/flow/registry.py` | `ENTRIES`, `registry()`, `by_category()` |
| `litedsp/flow/metadata.py` | `reflect()`, `BlockSpec`, the parameter glossary |
| `test/test_metadata_policy.py` | Defaults, vocabulary, latency and `ValueError` policy |
| `test/test_bypass.py` | Bypass passthrough under random stalls |

The next chapters describe the families: [Generation and mixing](#generation-mixing),
[Filters and rate change](#filters-rate), [Level control and analysis](#level-analysis),
[Communications blocks](#comm) and [Stream utilities and host links](#stream-frontend).
