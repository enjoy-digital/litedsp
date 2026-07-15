# Timestamped Streams

LiteDSP timestamps at the **edges** and computes time everywhere else. Time is never threaded
through the DSP blocks: no block payload grows a time field, no filter needs to know what time
it is. Instead:

- one `LiteDSPTimeCore` free-runs as the design's single time reference (a 64-bit sample/cycle
  counter, host-settable, PPS-disciplinable);
- a `LiteDSPTimestamper` (or the packetizer's timestamp header) latches that count where
  samples **enter** the system;
- every block declares `self.latency` (see `doc/interfaces.md`), so the absolute time of any
  sample anywhere in a chain is *ingress time + sample index + sum of the latencies crossed*.

This is the lean version of what VITA-49 does with per-packet integer timestamps: the field
set of the packet header below is VITA-49-inspired, but the format is explicitly **not**
VITA-49 wire-compliant (no class ID, no fractional-seconds words, no trailer).

## Blocks

| Block | Location | Role |
|---|---|---|
| `LiteDSPTimeCore` | `litedsp/stream/timestamp.py` | Free-running 64-bit counter. CSR set (`set_time`), atomic read (`latch` then `time`), PPS input latched into `pps_time` (+ optional IRQ per PPS edge, `with_irq=True`). CSR-only: not in the flow palette. |
| `LiteDSPTimestamper` | `litedsp/stream/timestamp.py` | Passthrough (latency 0) that adds `timestamp`/`stream_id` stream *params* (`litedsp.common.time_param_layout`) to its source. Latches the parent-connected `time` input at each frame `first` when framing is present (all samples of a frame carry the frame's ingress time); tags every sample with its own ingress time on an unframed stream. |
| `LiteDSPTimeUntagger` | `litedsp/stream/timestamp.py` | Strips the params back to plain I/Q (latency 0) — the boundary into time-agnostic blocks. |
| `LiteDSPIQPacketizer(with_timestamp=True)` | `litedsp/frontend/packet.py` | Prepends the 128-bit timestamp header to every packet (header layout below). Default off: bit-identical to the headerless format. |
| `LiteDSPIQDepacketizer(with_timestamp=True)` | `litedsp/frontend/packet.py` | Consumes the header and tags the I/Q source with the recovered `timestamp`/`stream_id` params. |

The tags ride in the stream's **param** layout, not the payload: plain blocks cannot accept
them, which is deliberate — strip with `LiteDSPTimeUntagger` (or
`connect(..., omit={"timestamp", "stream_id"})`) before entering a DSP chain. Only the edges
know about time.

```python
self.time_core   = LiteDSPTimeCore()
self.timestamper = LiteDSPTimestamper(stream_id=1)
self.comb += self.timestamper.time.eq(self.time_core.count)
```

`LiteDSPTimeCore` counts **cycles**, which equal samples at the canonical 1 sample/cycle of a
free-flowing chain; latch the timestamper at the converter boundary (before any elastic
buffering) so the count *is* the sample count. The host disciplines the epoch by writing
`set_time` and verifies/calibrates the rate against `pps_time` deltas (`TimeCoreDriver` in
`litedsp/software/drivers.py`: `read_time()`, `set()`, `read_pps_time()`).

## Recovering absolute sample time

For a chain of fixed-latency blocks (each `self.latency`, reflected as `BlockSpec.latency`),
the time of the sample observed at any point is back-computed:

```
ingress_time(sample k of a tagged frame) = timestamp + k
time at block N's output               = ingress_time + sum(latency of blocks 1..N)
```

Worked example — an RX DDC chain (default palette latencies):

```
ADC -> Timestamper -> DDC(dec=8) -> Gain -> FIR(complex) -> Packetizer -> host
          lat 0         lat 1       lat 1      lat 3
```

The host receives a packet whose header says `timestamp = T`, `stream_id = 1`. Sample `k` of
that packet left the FIR at `T + k` on the *decimated* time base; walking back through the
declared latencies, it entered the chain at ADC count

```
t_adc(k) = (T - (1 + 1 + 3)) + 8*k        # sum(BlockSpec.latency), then undo the rate change
```

Two bookkeeping rules when walking a chain:

- **Rate changers** (decimators/interpolators) scale the sample index (`k -> R*k` / `k -> k/L`)
  in addition to their own latency; the declared latency is counted at the block's own beat.
- **Elastic blocks** (CDC/FIFOs, `latency = 0`) add no *sample-index* offset — the recipe
  counts samples, not wall-clock stall cycles. Data-dependent blocks (`latency = None`) break
  the fixed-latency recipe; re-timestamp after them if sample-accurate time is needed
  downstream.

This recipe is pinned by `test/test_timestamp.py` (`TestTimeRecovery`): a tagged burst crosses
`gain -> fir_complex` and the recovered ingress time (`egress_tag - sum(BlockSpec.latency)`)
matches the recorded acceptance time of every sample exactly (+-0 samples).

## Packet timestamp header

`LiteDSPIQPacketizer(with_timestamp=True)` prepends one 128-bit header per packet, serialized
LSB-first into `word_width`-bit words (like the sample packing; `word_width` must divide 128).
The `time` input Signal is latched when each packet's first sample arrives; `stream_id` is
CSR-settable.

| Bits | Field | Value |
|---|---|---|
| [7:0] | `magic` | `0xDA` (`TIMESTAMP_MAGIC`) |
| [15:8] | `version` | `0x01` (`TIMESTAMP_VERSION`) |
| [23:16] | `stream_id` | 8-bit stream identifier |
| [31:24] | `reserved` | 0 |
| [63:32] | `count` | samples in this packet (the framer's runtime `length`) |
| [127:64] | `timestamp` | `LiteDSPTimeCore` count at the packet's first sample |

With the default 32-bit words a packet is `[hdr0, hdr1, hdr2, hdr3, payload...]` with `first`
on `hdr0` and `last` on the final payload word. `LiteDSPUDPIQStreamer` /
`LiteDSPUDPIQReceiver` plumb `with_timestamp` through, so each UDP datagram starts with the
header. With `with_timestamp=False` (default) the word stream is bit-identical to the
historical headerless format (pinned by `test/test_timestamp.py`).
