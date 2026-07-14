# Squelch

`LiteDSPSquelch` — `litedsp.level.squelch` — category `level`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Mute the I/Q stream when instantaneous power ``I**2 + Q**2`` is below threshold.

Hysteresis: opens above ``open_threshold``, closes below ``close_threshold`` (set
``close < open``). When closed, the output is zeroed (samples still flow). ``open`` status
reflects the gate state. With ``with_irq=True``, gate open/close edges raise interrupts
(``ev.opened`` / ``ev.closed``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `open_threshold` (read-write, 33 bits)

Open the gate at/above this power.

### `close_threshold` (read-write, 33 bits)

Close the gate below this power (set < open for hysteresis).

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `open` | `0` | Gate open. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_squelch.py` (bit-exact/SNR under randomized backpressure).
