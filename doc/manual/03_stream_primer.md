# Streams, latency and rates {#stream-primer}

This chapter explains how samples move from one LiteDSP block to the next. It covers the stream
handshake and the rule that a block never drops or duplicates a sample, then latency and how
parallel branches are kept aligned, then frames. It ends with rate change: decimation,
interpolation and resampling.

The streams are the LiteX stream endpoints, so a reader who knows LiteX can skim the first
sections. [Block contract](#architecture) gives the complete rules every block follows; this
chapter explains the ideas behind them.

## The valid/ready handshake {#pri-handshake}

Every LiteDSP block exchanges samples through LiteX stream endpoints (`stream.Endpoint`): a
`sink` for its input and a `source` for its output. Blocks with several inputs have `sink_a` and
`sink_b`, as the mixer, or a list `sinks`, as the combiner. An endpoint is a bundle of signals,
listed in the table below.

| Signal | Direction | Meaning |
|------------|-------------------|--------------------------------------------------------|
| `valid` | Producer to consumer | The payload holds a sample this cycle |
| `ready` | Consumer to producer | The consumer takes the sample this cycle |
| payload | Producer to consumer | The sample fields: `i` and `q`, or `data`, as the layout defines |
| `first` | Producer to consumer | This beat is the first of a frame |
| `last` | Producer to consumer | This beat is the last of a frame |
| param | Producer to consumer | Per-frame fields that ride next to the payload |

A sample moves on a clock edge where both `valid` and `ready` are high: this is one *beat*. When
`valid` is high and `ready` low, the producer must hold the same sample until the consumer takes
it. The figure below shows three samples, the second one held for one cycle.

![The valid/ready handshake. A beat transfers on each cycle where valid and ready are both high
(dark cells): A, then B, then C. On the third cycle ready is low, so the producer holds B (light
cell) and B transfers one cycle later.](pri_handshake.svg)

The payload layout comes from `litedsp/common.py`: `iq_layout` for complex samples,
`real_layout` for real ones, and specialized layouts for the other families. [Block
contract](#architecture) lists them all.

## Backpressure {#pri-backpressure}

A consumer that drops `ready` stops the producer: this is *backpressure*. It travels upstream,
block by block, until it reaches a block that can wait, such as a FIFO, or a source that can
pause. A converter cannot pause, so a chain fed by a converter must keep up on average and
absorb short stalls in a FIFO.

Every LiteDSP block honours backpressure; the few documented exceptions, such as the RMS meter,
are listed with their block. The rule of the block contract is strict: under any pattern of
stalls, a block must not drop a sample and must not duplicate one.

A filter whose history advanced on a stalled cycle would compute with a sample twice; a decimator
that counted a stalled cycle would keep the wrong sample. Both are silent errors that only show
under backpressure.

The unit tests check this rule. The stream drivers of `test/common.py` insert random idle cycles
on the input (`throttle`) and drop `ready` at random on the output (`ready_rate`); `run_stream`
does both by default. A block whose output under these random stalls differs from its golden
model fails. [Verification](#verification) describes the tests.

Two more rules keep chains safe. A serial block's `sink.ready` must not depend on its
`sink.valid`, or two connected blocks can form a combinational loop. A stream cannot be wired to
two consumers, since it has a single `ready`: `LiteDSPSplit` duplicates it. Each branch takes
the sample when it is ready, possibly in a different cycle from the others, and the split
consumes its input once every branch has taken it. All branches see exactly the same beats, and
the slowest branch paces the stream. The `valid` of a branch never waits for a `ready`, so a
consumer that raises `ready` only after `valid`, as AXI-Stream allows, works behind it.

## Elastic pipelines {#pri-elastic}

A pipelined block holds several samples at once, one per register stage. Under backpressure the
whole pipeline must freeze, or samples in flight would be overwritten. The simple way is a
common clock enable, often called `adv` in LiteDSP: the pipeline advances when the output slot
is free or being consumed, `source.ready | ~source.valid`, and `sink.ready` follows.

Stateful blocks need one more care. A FIR filter keeps a history of past samples, and that history
must only advance on a real input transfer, `sink.valid & sink.ready`.

The arithmetic stages behind it advance on every free output slot, so they drain idle cycles as
bubbles, which never enter the history. LiteDSP calls this an *elastic* pipeline; [Flow
control](#arch-flow) shows the reference code of the FIR filter.

Stateless blocks, which compute each output from one input only, need no history. For them the
block contract allows the LiteX `stream.PipelinedActor`, which does the handshake on its own.

## Latency in samples {#pri-latency}

The *latency* of a block is the delay between a sample entering it and the corresponding result
leaving it. Every LiteDSP block exposes it as `self.latency`, counted in samples.

With one sample per clock and no stall, the latency in samples is also the number of clock
cycles. A stall freezes the pipeline: it delays the result in time, but not in samples.

Some blocks have no fixed latency: their delay depends on the data or on a phase, as in a
resampler. They set `self.latency = None` explicitly. A composite block, such as the DDC, sets
its latency from its stages; [Latency](#arch-latency) gives the rules and their tests.

Latency matters for two reasons. A control loop, such as an AGC, sees its correction late by the
latency of the loop. And two branches that recombine must carry the same samples at the same
time, which is the subject of the next section.

## Delay balancing {#pri-delay-balance}

When a stream splits into two branches that later recombine, each branch delays its samples by
its own latency. The joining blocks consume one beat from each input together, so sample n of one
branch always meets sample n of the other. If a filter of latency 8 sits on one branch only, the
short branch waits for the long one at every sample, and the chain loses throughput.

The fix is to delay the shorter branch by the difference, here 8 samples. `LiteDSPDelay`
(`litedsp/stream/delay.py`) is that delay: `depth` register stages, any layout, a latency equal
to its depth. With equal latencies both branches deliver their samples in the same cycle, and the
join runs at one sample per clock.

The flow builder does this automatically: it sums the latencies along each path of a netlist and
inserts a delay of the exact deficit on the shorter branches of every join. [Flow, generator, GUI
and host software](#tooling) describes the flow.

## Bypass {#pri-bypass}

A bypass lets a block pass its input through unchanged, to compare a chain with and without it at
run time. Most in-line blocks that keep their layout have a `bypass` control; [Bypass](#arch-bypass)
lists which have a register.

In the blocks built with the shared `add_bypass` helper, the bypass path is delay-matched: the
sample comes out with the same latency as a processed one, and the bypass select travels with its
beat. A beat accepted while `bypass` is set comes out unprocessed, whatever the control does while
it is in flight, so the switch lands on an exact beat boundary. The figure below shows the switch
on a block of latency 1. The complex FIR is the exception ([Known issues](#intro-known-issues)).

![Delay-matched bypass of a block of latency 1 (`add_bypass`). Beats x0 and x1, accepted with
bypass low, come out processed; beats x2 onwards, accepted with bypass high, come out unchanged one
cycle later. No beat is lost or repeated at the switch.](pri_bypass.svg)

## Frames {#pri-framing}

Some data come in groups: the N samples of an FFT, a captured record, a packet. A *frame* is such a
group of consecutive beats.

LiteDSP marks frames with the `first` and `last` signals of the endpoint: `first` is high on the
first beat of the frame and `last` on its last beat. The figure below shows a frame of four samples.

![A framed stream. The frame s0 to s3 is delimited by first on its first beat and last on its
last beat; valid governs every beat as usual.](pri_framed.svg)

The window, PSD, capture and framer blocks use frames: `LiteDSPWindow` marks a frame every `n`
samples, and `LiteDSPPSD` emits each spectrum as a frame. Values that are constant over a frame,
such as a timestamp or the block floating-point exponent of the FFT, ride in *param* fields next
to the payload, beat-aligned like `first` and `last`.

Most processing blocks, the FIR filter, the mixer, the CIC and the FFT among them, do not carry
`first` and `last` through. The streaming FFT counts its frames from reset instead, and the blocks
after it skip its pipeline fill (the `fft_latency` argument of `LiteDSPPSD` and
`LiteDSPBitReverse`) to find the frame start. [Block contract](#architecture) gives the rules
per family.

## Decimation {#pri-decimation}

Lowering the sample rate by an integer R is *decimation*: keep one sample out of R. Dropping
samples is not enough. The output rate is fs/R, so its Nyquist limit is fs/(2R), and any signal
between fs/(2R) and fs/2 would alias into the output band. A low-pass filter must remove it
first, as the figure below shows.

![Decimation and interpolation. A decimator filters at the input rate, then keeps one sample out
of R. An interpolator inserts R - 1 zeros between samples, then filters at the output
rate.](pri_multirate.svg)

Filtering at the input rate then discarding R - 1 outputs out of R wastes work. Efficient
decimators compute only the outputs they keep: the polyphase FIR and the CIC filter, both
described in [Digital filters](#filter-primer). On the stream, a CIC decimator accepts a sample
on every cycle and emits once per R accepted samples, as the figure below shows; the polyphase FIR
decimator accepts R samples, then stalls its input while it computes the output.

![Decimation by 4, from a Migen simulation of LiteDSPCICDecimator. The sink takes a sample on
every cycle; the source emits one sample, y0 then y1, for every four accepted
inputs.](pri_decimator.svg)

`LiteDSPDownsampler` alone has no filter: it is the "keep 1 of R" step, for a stream that is
already band-limited. [Rate family](#fr-rate) lists the decimators.

## Interpolation {#pri-interpolation}

Raising the sample rate by an integer R is *interpolation*. The simple way inserts R - 1 zeros
between samples. The result has the right rate, but its spectrum holds R - 1 copies of the
original band, the *images*, centred on multiples of the old sample rate. A low-pass filter after
the insertion removes them.

Zero insertion also divides the average amplitude by R, so an interpolation filter has a gain of
R in its passband. On the stream, an interpolator accepts one input sample, emits R outputs,
then accepts the next: its input stalls while it drains, as the figure below shows.

![Interpolation by 4 (`LiteDSPUpsampler`; the CIC interpolator has the same steady state after a
two-sample fill). The sink is ready one cycle out of four, so x1 waits (light cells) until x0 has
produced its four outputs; the source emits a sample on every cycle.](pri_interpolator.svg)

The interpolators mirror the decimators; `LiteDSPUpsampler` has no filter and repeats each
sample, or inserts zeros.

## Rational and arbitrary resampling {#pri-resampling}

A ratio such as 3/2 is the combination of an interpolation by L = 3 and a decimation by M = 2.
The interpolator comes first, so that no band is lost, and a single low-pass filter at the high
rate serves as both anti-image and anti-alias filter. Its cutoff is set by the larger of L and M.

`LiteDSPRationalResampler` works this way; its latency depends on the phase, so it declares
`None`.

Some ratios are not a small fraction, or must change at run time, or are not rational at all. An
*arbitrary* resampler computes each output at a fractional position between input samples, by
interpolating a smooth curve through the neighbouring samples. A phase accumulator advances by
the ratio for each output and tells when to consume the next input.

`LiteDSPArbResampler` works this way, with the Farrow interpolator described in [Fractional
delay and the Farrow structure](#pri-farrow). Its `ratio` is f_in/f_out: below 1.0 it
interpolates, above 1.0 it decimates, and a decimating use needs an anti-alias filter in front.
Several channels at the same rate can also share one decimating engine, the resampler farm.
[Filters and rate change](#filters-rate) describes these blocks and their parameters.

Where to go next: [Digital filters](#filter-primer) for the filters behind each rate change,
[Block contract](#architecture) for the full stream rules.
