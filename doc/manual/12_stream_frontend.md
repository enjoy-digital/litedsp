# Stream utilities and host links {#stream-frontend}

This chapter describes the blocks that move samples rather than process them: routing and fan-out,
buffers and clock domain crossings, framing, register access, capture and DMA, timestamps, the
converter interfaces and the packet links to a host.

Read it when you assemble a chain, connect it to a converter, or bring its samples back to
software. The contract every block follows is in [Block contract](#architecture).

## At a glance {#str-glance}

| Group | Classes | Files |
|-----------------|---------------------------------------|--------------------------------------------|
| Routing | Split, combine, channel and TDM mux and demux, I/Q operations, delay | `split.py`, `combine.py`, `route.py`, `ops.py`, `delay.py` |
| Buffers and adapters | Skid buffer, FIFO, clock domain crossing, pack and unpack, format and lane adapters | `buffer.py`, `fifo.py`, `adapt.py`, `convert.py` |
| Framing | Framer, deframer | `framing.py` |
| Register access | Register source, register sink, register reader, null sink | `csr_io.py` |
| Capture and DMA | Capture, DMA capture, DMA replay | `capture.py`, `dma.py` |
| Timestamps | Time core, timestamper, time untagger | `timestamp.py` |
| Converters | ADC, DAC and bitstream interfaces | `converter.py` |
| Host links | I/Q packetizer and depacketizer, UDP I/Q streamer and receiver | `packet.py`, `udp.py` |

The files are in `litedsp/stream/`, except the converters and host links, in `litedsp/frontend/`.
The host drivers `CSRReaderDriver`, `CaptureDriver`, `CaptureMemoryReader`, `DMADriver` and
`TimeCoreDriver` are in `litedsp/software/drivers.py`.

The 23 blocks of the stream family are registry blocks, with datasheets in the [block
catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md) and registers in
[Stream registers](#reg-stream). The DMA blocks, the register reader, the time core, the lane
adapters, the format converters and the frontend classes are not in the registry: they are used from
Python in a SoC.

Most of these blocks have a latency of 0: they forward the handshake combinationally or are
elastic, and add no sample-index offset. The combiner and the delay register their output
(latency 1 by default). The capture and the register access blocks have no fixed latency
(`None`).

## Routing and fan-out {#str-routing}

A chain that branches needs a block that copies a stream, and a chain that joins needs a block
that waits for all its inputs. Both keep the branches in step: each output of a split sees every
sample, and a join takes one sample from each input together.

| Class | Key | What it does |
|----------------------------------|------------------------|------------------------------------------|
| `LiteDSPSplit` | `split` | Copies one stream to `n` sources; each takes every sample |
| `LiteDSPCombine` | `combine` | Sums `n_channels` streams with per-channel enable and saturation |
| `LiteDSPChannelMux` | `channel_mux` | Selects one of `n` sinks with `sel`; the others are held |
| `LiteDSPChannelDemux` | `channel_demux` | Routes the sink to one of `n` sources with `sel` |
| `LiteDSPTDMMux` | `tdm_mux` | Interleaves mono streams into one channel-tagged stream |
| `LiteDSPTDMDemux` | `tdm_demux` | Routes each beat of a tagged stream to `sources[channel]` |
| `LiteDSPDelay` | `delay` | Delays a stream by `depth` samples to align branches |
| `LiteDSPConjugate` | `conjugate` | Negates Q: the complex conjugate |
| `LiteDSPSwapIQ` | `swap_iq` | Swaps I and Q: a spectrum mirror |
| `LiteDSPNegate` | `negate` | Negates I and Q |
| `LiteDSPIQAdd` | none | Saturating sum of two I/Q streams, such as signal plus noise |

The split is an eager fan-out: each output takes the current sample when it is ready, then holds
its `valid` low until every other output has taken it too. The input sample is consumed once all
the outputs have taken it, so every output sees exactly the same transfers and the slowest branch
paces the stream. With every output ready, a sample passes in the same cycle.

The `valid` of an output never depends on a `ready`. A consumer that waits for `valid` before it
raises `ready`, as AXI-Stream allows, works, and two branches of one split may feed the two inputs
of one joining block, such as the mixer or the combiner.

The combiner joins its inputs synchronously: it takes one sample from each input in the same
cycle, only when all are valid. A disabled channel adds zero but is consumed all the same, so the
inputs stay in step. Like every join, it pairs the k-th samples of its inputs whatever the latency
of each branch; a latency difference only lowers the throughput.

The sum grows by `ceil(log2(n_channels))` guard bits and is saturated back to the sample width, so
it never wraps. Its `enable` register is a mask, bit k for channel k.

The channel mux holds the `ready` of the unselected inputs low: they wait, they are not drained.
The demux holds the `valid` of the unselected outputs low, so no sample is copied to them.

The TDM mux takes beat k of each frame from input k and tags it `channel = k`; a slow input
therefore stalls the whole frame, which keeps the channels of a converter aligned.

The delay is a chain of registers that advance together with the stream. Under backpressure all
branches stall the same way, so a delay of `depth` samples stays `depth` samples. The flow inserts
delays automatically on reconvergent paths ([Latency](#arch-latency)).

The routing blocks take a `layout` argument, so they also carry real, three-phase or TDM streams.
The I/Q adder follows the `first` and `last` of its `sink_a` input.

## Buffers and adapters {#str-buffers}

These blocks change the timing or the shape of a stream without changing the samples.

| Class | Key | What it does |
|------------------------------------------------|---------------------|-------------------------------|
| `LiteDSPSkidBuffer` | `skid_buffer` | Registers both the valid and the ready paths |
| `LiteDSPStreamFIFO` | `stream_fifo` | Synchronous first-word-fall-through FIFO, `depth` beats |
| `LiteDSPIQClockDomainCrossing` | `cdc` | Asynchronous FIFO between `cd_from` and `cd_to` |
| `LiteDSPIQPack` | `iq_pack` | Packs `ratio` I/Q samples into one wide `data` word |
| `LiteDSPIQUnpack` | `iq_unpack` | Unpacks a wide word into `ratio` I/Q samples |
| `LiteDSPOffsetBinaryToTwos` | none | Offset binary to two's complement (flip the MSB) |
| `LiteDSPTwosToOffsetBinary` | none | Two's complement to offset binary |
| `LiteDSPIQSerialToParallel` | none | Gathers `n_samples` samples into one parallel beat |
| `LiteDSPIQParallelToSerial` | none | Spreads a parallel beat into `n_samples` samples |

The skid buffer cuts a long combinational path, on `valid` and on `ready`, without losing
throughput. Insert one when timing fails between two blocks.

The FIFO absorbs bursts. It backpressures when it is full, and a sticky `overflow` status bit
records that the upstream block presented a sample while the FIFO could not take it.

The FIFO itself loses nothing: the flag also sets on an ordinary stall
of an upstream block that can wait, and only a reset of the block clears it. A source that cannot
stall, such as a converter, would have lost that sample, so size `depth` to the longest stall of the
consumer.

The clock domain crossing wraps a LiteX asynchronous FIFO. Its `depth` absorbs the rate jitter
between the two domains. [Integration](#integration) shows where to place it between a converter
and the system clock.

The packer puts the first sample in the least significant bits of the word, which is the order
of the DMA blocks, of the packetizer and of the host tools. The lane adapters are described in
[Parallel variants](#arch-parallel).

## Framing {#str-framing}

Fixed-size frames are needed by DMA engines, by AXI-Stream consumers that expect `tlast`, and by
the host packet links. The framer passes the samples through and sets `first` on sample 0 and
`last` on sample `length - 1` of each frame. Its `length` register sets the frame size at run
time, below `max_length`.

The deframer does the reverse check. It passes the samples through, counts the completed frames
on `last` in its `frames` register, and derives `first` again after each `last`.

## Register access {#str-csr}

Four small blocks connect a stream to the register bus, for tests, slow control and bring-up
without a DMA engine.

| Class | Key | Registers | What it does |
|------------------------------|--------------------|-------------------|-------------------------------|
| `LiteDSPCSRSource` | `csr_source` | `sample`, `push` | Emits one sample per write of `push` |
| `LiteDSPCSRSink` | `csr_sink` | `last`, `count`, `clear` | Always ready; keeps the last sample and counts |
| `LiteDSPCSRReader` | none | `data`, `valid`, `pop` | Holds the stream until software pops each sample |
| `LiteDSPNullSink` | `null_sink` | `count`, `clear` | Always ready; counts and discards |

The register reader, `LiteDSPCSRReader`, is the slow but simple way out of a chain. Its `ready` is
the write strobe of `pop`, so the stream waits for the software. The software reads `valid`, reads
`data` (I in the low 16 bits, Q in the high 16 bits), then writes `pop`, one sample at a time.
`CSRReaderDriver` of `litedsp/software/drivers.py` runs this loop.

## Capture {#str-capture}

A chain runs continuously, but a host reads slowly. The capture block bridges the two: it records
a burst of samples into a RAM on a trigger, then lets the host read them at its own pace. The
figure below shows the ways out of a chain toward the host.

![Ways out of a chain: the capture records a burst on a trigger and is read through a register reader
or a Wishbone window; the DMA capture writes a continuous stream into memory. The host reaches
both through the SoC bus and a bridge.](str_capture.svg)

The capture is a tap: its `sink` is always ready, so it never slows the live stream. It waits in
an armed state, triggers on a rising edge of I above `threshold` or on the `force` control,
records `depth` samples, then presents them on its `source` with `first` and `last`. It re-arms
once its `source` has delivered the whole buffer.

| Register | Access | Content |
|------------------|-----------|-----------------------------------------------------------------------|
| `threshold` | write | Trigger level, compared with I |
| `force` | write | Trigger without the threshold while set |
| `status` | read | `armed`: waiting for the trigger; `done`: buffer ready or being read |

The buffer can be read in two ways. The `source` stream feeds a register reader, which works
through any bridge, even a UART. With `with_wishbone=True`, the capture also exposes its RAM as a
read-only Wishbone window, one sample per 32-bit word, which a host reads in bursts over
Etherbone. With `with_irq=True`, the rising edge of `done` raises an interrupt.

The Wishbone window reads the buffer without consuming the `source` stream. A capture read only
through the window stays in readout and ignores the next trigger until its `source` is drained,
by the register reader or by a reset of the block ([Known issues](#intro-known-issues)).

The spectrum bench (`bench/spectrum.py`) uses both readouts on the same capture:

```python
self.capture = LiteDSPCapture(depth=capture_depth, data_width=16, with_wishbone=True)
self.reader  = LiteDSPCSRReader(data_width=16)
# Fast readout: the capture buffer as a memory-mapped window (one sample per word).
self.bus.add_slave(name="capture_mem", slave=self.capture.bus,
    region=SoCRegion(origin=0x3000_0000, size=self.capture.mem_size, cached=False))
self.comb += [
    self.ddc.source.connect(self.capture.sink),
    self.capture.source.connect(self.reader.sink),
]
```

On the host, `CaptureDriver` arms and forces the trigger, `CSRReaderDriver` drains the stream,
and `CaptureMemoryReader` reads the Wishbone window by the name of its memory region
(`capture_mem`). The capture packs I and Q into one 32-bit word, so it takes samples of 16 bits
or less.

### DMA capture and replay {#str-dma}

The capture is limited to a RAM inside the FPGA. To record or play long streams, the DMA blocks
move samples between a stream and a window of system memory, at a sustained rate.

`LiteDSPDMACapture` packs the I/Q samples into memory words with a `LiteDSPIQPack` and writes
them with a DMA writer; `LiteDSPDMAReplay` reads a window back and unpacks it, and can loop for a
continuous replay. Each takes exactly one backend:

- `bus=`, a Wishbone master, with the LiteX DMA of `litex.soc.cores.dma`; add it to the SoC with
  `soc.bus.add_master()`. This fits SoCs without DRAM and low sample rates.
- `port=`, a LiteDRAM native port from `soc.sdram.crossbar.get_port()`, with the LiteDRAM DMA, for
  sustained rates with wide words.

The memory word width must be a multiple of the I/Q sample width; a 32-bit Wishbone bus carries
one 16-bit I/Q sample per word. The control is the LiteX DMA register set: `base` and `length`
in bytes, `enable`, `done`, `loop` and `offset`. With the Wishbone backend and
`with_csr=False`, these are plain control signals instead; the LiteDRAM backend always uses
registers.

While the DMA is disabled, the Wishbone writer accepts and drops the incoming samples; the
LiteDRAM writer does not accept them, so the stream waits.

Once a transfer without `loop` is done,
both writers stop accepting samples until the DMA is disabled and enabled again. The Wishbone
writer also ends a transfer at the `last` of a framed stream: strip the framing or use `loop` for a
continuous recording. `DMADriver` of `litedsp/software/drivers.py` programs a window and
waits for `done`.

## Timestamps {#str-timestamps}

LiteDSP timestamps samples at the edges of a design and computes time everywhere else. No block
of a chain carries a time field and no filter needs to know the time. Instead:

- one time core runs freely as the single time reference of the design: a 64-bit counter that the
  host can set, with a PPS input that latches the count for the host to measure the sample clock
  (synchronize `pps` to the system clock first);
- a timestamper, or the timestamp header of the packetizer, latches that count where samples
  enter or leave the system;
- every block declares its latency, so the time of a sample anywhere in a chain is its ingress
  time, plus its index, plus the latencies it crossed.

The figure below shows where the count is latched in a receive chain.

![Timestamps at the edges: the time core count is latched by the timestamper at ingress and by
the packetizer at egress; the untagger strips the tags, and the blocks in between carry no time,
only their declared latency.](str_timestamps.svg)

The idea is close to the integer timestamps of VITA-49, in a lean form. The fields of the packet
header are inspired by VITA-49, but the format is not VITA-49 compliant on the wire: it has no
class identifier, no fractional-seconds words and no trailer.

### Blocks {#str-time-blocks}

| Class | Role |
|------------------------------------|----------------------------------------------------------------|
| `LiteDSPTimeCore` | Free-running 64-bit counter: set, atomic read, PPS latch, optional PPS interrupt; registers only, not in the flow palette |
| `LiteDSPTimestamper` | Passthrough with latency 0 that adds the `timestamp` and `stream_id` stream parameters |
| `LiteDSPTimeUntagger` | Strips those parameters, latency 0: the way back into plain blocks |
| `LiteDSPIQPacketizer` | With `with_timestamp=True`, prepends a 128-bit timestamp header to each packet |
| `LiteDSPIQDepacketizer` | With `with_timestamp=True`, consumes the header and tags its output with it |

The timestamper reads the `time` input that its parent connects to the time core. On a framed
stream it latches the time at each `first` and holds it for the whole frame, so sample k of a
frame has the time `timestamp + k`.

On a stream without framing, each sample carries its own ingress time. The ingress time is the
cycle of the transfer, `valid` and `ready` high.

The tags ride in the stream parameters, not in the payload. A plain block cannot accept them,
which is deliberate: strip them with the untagger, or with
`connect(..., omit={"timestamp", "stream_id"})`, before a chain. Only the edges know about time.

```python
self.time_core   = LiteDSPTimeCore()
self.timestamper = LiteDSPTimestamper(stream_id=1)
self.comb += self.timestamper.time.eq(self.time_core.count)
```

The time core counts cycles. A cycle is a sample when the chain runs freely at one sample per
clock, so latch the timestamper at the converter boundary, before any elastic buffer, to make the
count the sample count.

| Register | Access | Content |
|----------------|-----------|-------------------------------------------------------------------------|
| `set_time` | write | Loads the counter, on the write of its last word |
| `latch` | write | Freezes the counter into `time`; write it before reading `time` |
| `time` | read | Frozen count, read atomically over several register words |
| `pps_time` | read | Count at the last rising edge of `pps`, stable between pulses |

The host sets the epoch by writing `set_time`, and checks or calibrates the sample clock from the
difference between two `pps_time` readings. `TimeCoreDriver` of `litedsp/software/drivers.py`
offers `read_time()`, `set()` and `read_pps_time()`.

### Recovering the time of a sample {#str-time-recovery}

For a chain of fixed-latency blocks, the time of a sample seen at any point is computed back from
the declared latencies, which the registry reflects as `BlockSpec.latency`:

```text
ingress_time(sample k of a tagged frame) = timestamp + k
time at the output of block N            = ingress_time + sum(latency of blocks 1 to N)
```

A test pins this recipe at one sample per clock. In `test/test_timestamp.py`, a tagged burst
crosses a gain and a complex FIR, which carry no time, and is tagged again at the output.

For every sample, the output tag minus the sum of the two registry latencies equals the cycle at
which the sample was accepted at the input, with no error.

Two bookkeeping rules apply when walking a chain:

- a rate changer scales the sample index: through a decimator by `R`, output sample k corresponds
  to input sample `R*k`, and through an interpolator by `L` to input sample `k/L`. Count in input
  sample periods, and convert a block's latency, counted at its own beat, to that unit before
  adding it;
- an elastic block, such as a FIFO or a clock domain crossing, declares a latency of 0 and adds no
  sample-index offset: the recipe counts samples, not the cycles of a stall.

A block with a data-dependent latency (`None`) breaks the recipe. Timestamp the stream again
after it when the time of each sample matters downstream. Only the case without rate change is
covered by a test.

### Packet timestamp header {#str-time-header}

With `with_timestamp=True`, the packetizer prepends a 128-bit header to each packet. The header
is sent least significant bits first, in words of `word_width` bits, like the samples, so
`word_width` must divide 128. The `time` input is latched when the first sample of each packet
arrives; `stream_id` is a register.

| Bits | Field | Value |
|-------------|------------------|---------------------------------------------------------------------|
| [7:0] | `magic` | `0xDA` (`TIMESTAMP_MAGIC`) |
| [15:8] | `version` | `0x01` (`TIMESTAMP_VERSION`) |
| [23:16] | `stream_id` | 8-bit stream identifier |
| [31:24] | `reserved` | 0 |
| [63:32] | `count` | Samples in this packet (the runtime `length` of the framer) |
| [127:64] | `timestamp` | Time core count at the first sample of the packet |

With the default 32-bit words, a packet is `hdr0`, `hdr1`, `hdr2`, `hdr3`, then the payload words,
with `first` on `hdr0` and `last` on the last payload word.

The UDP streamer and receiver pass `with_timestamp` through, so each datagram then starts with the
header. With `with_timestamp=False`, the default, the word stream is bit identical to the format
without header; `test/test_timestamp.py` checks both.

## Converter interfaces {#fe-converters}

The frontend adapts converter words to the sample format of the chain. Whatever the converter
resolution, the chain sees full-scale Q1.15 samples, so the gains and thresholds downstream do
not depend on the converter.

| Class | Parameters | What it does |
|-------------------------------------------|----------------------------|-----------------------------|
| `LiteDSPADCInterface` | `adc_width`, `data_width`, `fmt` | Converter I/Q words to signed samples, MSB aligned |
| `LiteDSPDACInterface` | `dac_width`, `data_width`, `fmt` | Signed samples to converter words, rounded and saturated |
| `LiteDSPBitstreamInterface` | `clock_div`, `n_channels`, `dual_edge` | Modulator clock and 1-bit data pins to 1-bit streams |

The ADC interface flips the MSB when `fmt="offset_binary"` (the default; `"twos"` leaves it), then
shifts the word left by `data_width - adc_width` bits. The DAC interface narrows with `scaled()`,
which rounds and saturates, then re-encodes the format. Both have a latency of 0 and pass the
handshake and the framing through.

The bitstream interface serves 1-bit modulators: sigma-delta ADCs and PDM microphones. It
generates `mclk` at the system clock divided by `clock_div` (even, 4 or more) and samples the
synchronized data lines after each falling edge.

With `dual_edge=True`, each line carries two channels, one per edge, as PDM stereo does. Each
output keeps only its latest bit: a bit not consumed in time is overwritten and the sticky
`overrun` flag is set, so the line never stalls.

Vendor-specific capture logic, such as DDR inputs or deserializers, stays outside LiteDSP. Wrap it
into a raw I/Q stream at the sample clock, then feed the adapters, through a clock domain crossing
when the sample clock is not the system clock.

## Packets and host links {#fe-packets}

A host link carries words, not samples. The packetizer frames the sample stream every
`samples_per_packet` samples and packs the samples into `word_width`-bit words, first sample in
the least significant bits.

The resulting `data` and `last` stream maps onto a UDP payload in LiteEth, a host DMA word stream
such as the `dma.sink` of LitePCIe, or any AXI-Stream consumer with `tlast`. The depacketizer is
the exact inverse, for the host to FPGA direction.

| Class | Main parameters | Notes |
|-------------------------------------|--------------------------------|--------------------------------|
| `LiteDSPIQPacketizer` | `word_width`, `samples_per_packet`, `with_timestamp`, `stream_id` | `samples_per_packet` must be a multiple of the samples per word |
| `LiteDSPIQDepacketizer` | `word_width`, `with_timestamp` | Recovers the samples and the header tags |
| `LiteDSPUDPIQStreamer` | `udp`, `ip_address`, `udp_port`, `samples_per_packet` | One UDP datagram per packet |
| `LiteDSPUDPIQReceiver` | `udp`, `udp_port`, `fifo_depth` | Datagrams on `udp_port` to samples |

The UDP streamer chains a packetizer and the LiteEth stream-to-UDP transmitter, whose FIFO holds
one full packet. It takes the LiteEth UDP core and requests a user port on its crossbar, or
directly a `LiteEthUDPUserPort`, which keeps it simulable without the full stack. The receiver
chains the LiteEth UDP receiver and a depacketizer.

The UDP stream bench of [Boards and benches](#brd-stream) connects the streamer to the UDP core
of Etherbone, so one Ethernet link carries both the samples and the register accesses.

### Streaming to GNU Radio {#fe-gnuradio}

Without a header, the format of `LiteDSPUDPIQStreamer` is simple. A datagram holds
`samples_per_packet` samples, 256 by default, so 1024 payload bytes. Each 32-bit word is one
sample, I in bits 15 to 0 and Q in bits 31 to 16, first sample first. LiteEth sends the words least
significant byte first, so the bytes are interleaved 16-bit signed little-endian I and Q, the
"short" complex format of GNU Radio.

A stock GNU Radio flowgraph receives the stream with the blocks below; the scale factor maps Q1.15
full scale to plus or minus one.

| GNU Radio block | Parameters |
|------------------------------------|------------------------------------------------------|
| UDP Source | Port 6000, output type short, payload size 1024 |
| Interleaved Short To Complex | Vector input off, swap off, scale factor 32768.0 |
| QT GUI Waterfall or Frequency Sink | FFT size 64, sample rate of the front end |

With `with_timestamp=True`, each datagram starts with the 16-byte header of
[Packet timestamp header](#str-time-header), which the stock UDP source does not strip: keep the
headerless format for stock interoperation, or strip the header in a small Python block and turn
the timestamp into a stream tag.

To put a chain in a SoC and connect it to a converter, read [Integration](#integration); to build
a chain from a netlist, read [Flow, generator, GUI and host software](#tooling).
