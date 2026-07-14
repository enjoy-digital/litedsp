# Energy detector

`LiteDSPEnergyDetector` — `litedsp.analysis.detect` — category `analysis`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Signal-presence detector with an adaptive noise floor (CFAR-style).

Passes the I/Q stream through and asserts ``detect`` when instantaneous power exceeds the
estimated noise floor by ``2**threshold_log2``. The floor is a leaky average of power,
updated only while no signal is detected (so the signal does not raise the floor).
With ``with_irq=True``, a detection edge raises an interrupt (``ev.detect``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `avg_shift` | `10` | int | Leaky-average shift of the noise-floor tracker (``floor += (power - floor) >> avg_shift``); larger values track slower/smoother (time constant ~2**avg_shift samples). |
| `threshold_log2` | `3` | int | Detection threshold as a power-of-two ratio over the noise floor: detect when power > floor * 2**threshold_log2 (~3 dB per step). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `detect` | `0` | Signal present. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_detect.py` (bit-exact/SNR under randomized backpressure).
