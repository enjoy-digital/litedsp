# Quadrature encoder

`LiteDSPQuadratureDecoder` — `litedsp.motor.encoder` — category `motor`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Incremental encoder (A/B/Z) interface: position, direction, speed and electrical angle.

The A/B pins are synchronized, glitch-filtered (``filter_length`` identical samples) and
decoded at 4x resolution (every edge is a count); an illegal transition (both bits
changing) sets the sticky ``error``. ``position`` counts modulo ``counts_per_rev``; the
electrical position ``epos`` advances by ``pole_pairs`` per count (modulo
``counts_per_rev``) so ``angle = epos*angle_scale >> scale_frac + angle_offset`` with
``angle_scale = round(2**(angle_width + scale_frac) / counts_per_rev)`` -- a reciprocal
multiply, exact for power-of-two counts and within one LSB otherwise. The index pulse Z
(rising edge, when ``index_enable``) zeroes the position and sets ``index_seen``
(``ev.index`` with ``with_irq=True``; ``ev.error`` for illegal transitions). ``speed`` is
the signed count over the last ``window`` cycles (M-method). The angle stream is emitted
on ``sample`` (latest-wins, sticky ``overrun``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `angle_width` | `16` | int | Electrical angle width (full turn = 2**angle_width). |
| `position_width` | `16` | int | Position counter width (must hold ``counts_per_rev - 1``). |
| `speed_width` | `16` | int | Width of the signed per-window count. |
| `filter_length` | `2` | int | Glitch filter length in cycles (>= 1). |
| `scale_frac` | `16` | int | Fractional bits of ``angle_scale``. |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | angle |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `counts_per_rev` (read-write, 16 bits, reset `0x1000`)

Encoder counts per mechanical turn (4x decoded).

### `pole_pairs` (read-write, 8 bits, reset `0x1`)

Motor pole pairs.

### `angle_scale` (read-write, 32 bits, reset `0x100000`)

round(2**32 / counts_per_rev).

### `angle_offset` (read-write, 16 bits)

Electrical angle offset added to the output (encoder alignment).

### `window` (read-write, 24 bits, reset `0x10000`)

Speed measurement window in cycles.

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `invert` | `0` | Swap the counting direction. |
| `[1]` | `index_enable` | `0` | Z pulse zeroes the position. |
| `[2]` | `clear` | `0` | Clear error/index/overrun. (pulse) |

### `position` (read-only, 16 bits)

Mechanical count.

### `speed` (read-only, 16 bits)

Signed counts per window.

### `status` (read-only, 4 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `direction` | `0` | Last step was negative. |
| `[1]` | `index_seen` | `0` | Index pulse seen since clear. |
| `[2]` | `error` | `0` | Illegal transition since clear. |
| `[3]` | `overrun` | `0` | An angle sample was not consumed. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_encoder.py` (bit-exact/SNR under randomized backpressure).
