# Over-current trip

`LiteDSPOvercurrentTrip` — `litedsp.motor.sense` — category `motor`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Window comparator on a three-phase stream: combinational passthrough + sticky trip.

Any accepted sample with ``|phase| > threshold`` sets ``fault`` (sticky), the ``phase``
bit(s) that tripped and increments ``count``; ``clear`` releases them. Wire ``fault`` to
:class:`~litedsp.motor.pwm.LiteDSPPWM`'s ``fault`` input to switch the inverter off within
one cycle. ``with_irq=True`` adds ``ev.fault``. Latency 0.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | abc |
| `source` | source | abc |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `threshold` (read-write, 16 bits, reset `0x7fff`)

Trip magnitude (per-unit).

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear fault, phases and count. (pulse) |

### `status` (read-only, 4 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `fault` | `0` | Sticky trip. |
| `[3:1]` | `phase` | `0` | Phases that tripped (a, b, c). |

### `count` (read-only, 32 bits)

Trips since clear.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 228 | 36 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_sense.py` (bit-exact/SNR under randomized backpressure).
