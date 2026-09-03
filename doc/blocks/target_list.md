# Target list

`LiteDSPTargetList` — `litedsp.radar.detect` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Per-CPI target list buffer with host readback.

Buffers each CPI's burst of :func:`~litedsp.common.target_layout` records in a ping-pong RAM
of ``2 x max_targets`` entries: the terminator seals a bank (records beyond ``max_targets``
are dropped, counted and flagged by the sticky ``overflow``) and the sealed list is re-emitted
framed (records then the terminator with the count) while the other bank fills;
``sink.ready`` drops only when both banks are sealed. The host reads the last sealed list
through ``rd_index`` -> ``rd_range`` / ``rd_doppler`` / ``rd_data`` (one cycle later) and
``rd_count``; the list stays readable until the following CPI's terminator. The optional
``ev.list`` interrupt fires when a list is sealed. ``latency = None``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `max_targets` | `16` | int |  |
| `data_width` | `17` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `index_width` | `12` | int |  |
| `frac_bits` | `4` | int | Fractional bits of the coefficient/control fixed-point format. |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | target |
| `source` | source | target |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 20 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `max_targets` | `0` | List capacity. |
| `[19:16]` | `frac_bits` | `0` | Sub-bin fractional bits. |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the overflow flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `overflow` | `0` | Sticky: a list exceeded max_targets. |

### `index` (read-write, 4 bits)

Readback record index.

### `range` (read-only, 16 bits)

Record range (Q.frac_bits bins).

### `doppler` (read-only, 16 bits)

Record Doppler bin (Q.frac_bits).

### `data` (read-only, 17 bits)

Record cell value.

### `count` (read-only, 5 bits)

Records in the last sealed list.

### `cpi_count` (read-only, 32 bits)

Lists sealed since reset.

### `dropped` (read-only, 32 bits)

Records dropped since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 263 | 112 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_detect.py` (bit-exact/SNR under randomized backpressure).
