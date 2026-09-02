# Hall sensor decoder

`LiteDSPHallDecoder` — `litedsp.motor.encoder` — category `motor`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Three 120-degree Hall sensors -> sector, direction, speed and (interpolated) angle.

The synchronized/filtered ``hall`` code selects one of six 60-degree sectors (codes 0
and 7 set the sticky ``error`` once a valid code has been seen, so idle pins at power-up
do not flag); ``angle`` is the sector center (``sector*60 + 30``
degrees electrical, plus ``angle_offset``). With ``interpolate=True`` the time between
the last two sector edges (``period``, cycles) sets a per-cycle increment ``inc =
(2**angle_width/6 << 8)/period`` (serial divider, one per edge) and the angle ramps
from the sector start (or end, when running backwards), clamped at the sector boundary
until the next edge -- a 60-degree-resolution sensor becomes a smooth angle at constant
speed. ``direction`` follows the sector sequence; ``speed`` is the signed increment
(electrical angle units per cycle, Q.8); ``stall`` latches when the edge timer saturates.
The angle stream is emitted on ``sample`` (latest-wins, sticky ``overrun``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `angle_width` | `16` | int | Electrical angle width (full turn = 2**angle_width). |
| `timer_width` | `24` | int | Width of the sector-period timer (cycles between Hall edges). |
| `interpolate` | `True` | bool | Ramp the angle between edges from the measured sector period. |
| `filter_length` | `2` | int | Glitch filter length in cycles (>= 1). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | angle |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `angle_offset` (read-write, 16 bits)

Electrical angle offset added to the output (sensor alignment).

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `invert` | `0` | Swap the direction convention. |
| `[1]` | `clear` | `0` | Clear error/stall/overrun. (pulse) |

### `period` (read-only, 24 bits)

Cycles per sector (last edge).

### `speed` (read-only, 24 bits)

Signed angle units per cycle (Q.8).

### `status` (read-only, 7 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[2:0]` | `sector` | `0` | Current sector (0..5). |
| `[3]` | `direction` | `0` | Running backwards. |
| `[4]` | `error` | `0` | Invalid Hall code since clear. |
| `[5]` | `stall` | `0` | Sector timer saturated since clear. |
| `[6]` | `overrun` | `0` | An angle sample was not consumed. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 379 | 187 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_encoder.py` (bit-exact/SNR under randomized backpressure).
