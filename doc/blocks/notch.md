# Notch

`LiteDSPNotch` — `litedsp.filter.extra` — category `filter`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Tunable 2nd-order notch (zeros on the unit circle, poles at radius ``r``).

Notch frequency set at runtime by ``cos_w0`` (= cos(2*pi*f0), signed Q.``frac``). ``r`` (build
time, <1) sets the notch width. Direct-form-I biquad with round + saturate (per I/Q).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `frac` | `14` | int | Fractional bits of the control fixed-point format. |
| `r` | `0.96` | float | Pole radius (build time, 0 < r < 1), quantized to Q.frac. Closer to 1 = narrower notch but longer settling/ringing; too close to 1 risks quantization instability. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `cos_w0` (read-write, 16 bits)

cos(2*pi*f0), Q.frac.

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
