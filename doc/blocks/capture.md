# Capture (scope)

`LiteDSPCapture` — `litedsp.stream.capture` — category `stream`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Scope-like capture: on a trigger, record ``depth`` I/Q samples to RAM, then stream them out.

Taps the input (always ready, never backpressures the live stream). Triggers on a rising
edge of ``I`` past ``threshold`` or on a ``force`` pulse; captures ``depth`` samples, then
presents them on ``source`` and re-arms once read out. ``done`` is asserted while the
captured buffer is ready/being read out; with ``with_irq=True`` its rising edge raises an
interrupt (``ev.done``).

Readout paths: the ``source`` stream (feed a ``LiteDSPCSRReader`` for CPU-less bridges), or —
with ``with_wishbone=True`` / ``add_wishbone()`` — a read-only Wishbone window on the
buffer (``self.bus``, one sample per 32-bit word) for fast memory-mapped drains over
Etherbone (``soc.bus.add_slave(..., capture.bus, SoCRegion(size=capture.mem_size, ...))``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `depth` | `256` | int | Number of I/Q samples recorded per trigger. Sizes the capture RAM (one 32-bit word per sample, mem_size = 4*depth bytes) and the readout burst length. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |
| `with_wishbone` | `False` | bool | Add a read-only Wishbone window (``self.bus``) over the capture buffer for fast memory-mapped readout (e.g. over Etherbone) instead of CSR-paced streaming. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `threshold` (read-write, 16 bits)

Trigger level (I).

### `force` (read-write, 1 bit)

Force trigger.

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `armed` | `0` | Waiting for trigger. |
| `[1]` | `done` | `0` | Capture complete, buffer ready. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_capture.py` (bit-exact/SNR under randomized backpressure).
