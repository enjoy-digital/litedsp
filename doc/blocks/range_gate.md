# Range gate (PRI timer)

`LiteDSPRangeGate` — `litedsp.radar.timing` — category `radar`

latency: 1 sample · CSR: yes · bypass: no

## Overview

PRI / CPI timer and receive gate: turns a continuous I/Q stream into framed pulses.

A sample-domain counter ``t`` (it advances on every accepted input sample, so the timing is
exact under any valid/ready pattern) runs from 0 to ``pri - 1`` per pulse repetition
interval; ``n_pulses_cpi`` intervals make a coherent processing interval. Samples with
``gate_start <= t < gate_start + gate_len`` pass, framed (``first`` at the gate start,
``last`` at its end); the others are consumed and dropped. ``tx`` is high for
``pulse_width`` samples at the start of each interval (the transmit strobe), ``rx_gate``
mirrors the receive window and ``cpi_start`` pulses on the first sample of a CPI (IRQ
``ev.cpi``). Continuous operation with ``enable``; ``single`` runs exactly one CPI per
``trigger``. Latency 1 cycle; the output rate is ``gate_len / pri``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_range_bins` | `64` | int | Maximum gate length in samples (sizes the runtime ``gate_len``, reset to it). |
| `n_pulses` | `16` | int |  |
| `pri` | `128` | int |  |
| `gate_start` | `0` | int |  |
| `pulse_width` | `16` | int |  |
| `pri_width` | `24` | int |  |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `pri` (read-write, 24 bits, reset `0x80`)

Pulse repetition interval in samples.

### `gate` (read-write, 31 bits, reset `0x40000000`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[23:0]` | `start` | `0` | First received range bin (sample index in the interval). |
| `[30:24]` | `length` | `64` | Range bins per pulse (<= n_range_bins). |

### `pulse` (read-write, 29 bits, reset `0x10000010`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[23:0]` | `width` | `16` | Transmit strobe length in samples. |
| `[28:24]` | `n_pulses` | `16` | Pulses per CPI. |

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `enable` | `0` | Run continuously. |
| `[1]` | `single` | `0` | Run one CPI per trigger. |
| `[2]` | `trigger` | `0` | Start a CPI (single mode). (pulse) |

### `status` (read-only, 12 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `running` | `0` | Timer running. |
| `[11:8]` | `pulse_index` | `0` | Pulse within the CPI. |

### `pulse_count` (read-only, 32 bits)

Pulses since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 363 | 96 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_timing.py` (bit-exact/SNR under randomized backpressure).
