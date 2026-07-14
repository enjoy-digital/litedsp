# Log power (dB)

`LiteDSPLogPower` — `litedsp.level.logdb` — category `level`

latency: 2 samples · CSR: no · bypass: no

## Overview

Power-to-dB: ``10*log10(x) = 3.0103 * log2(x)`` (x is a power value, unsigned).

Internally a :class:`LiteDSPLog2` followed by a constant scale. Output is dB in Q?.``out_frac``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `in_width` | `32` | int | Width in bits of the unsigned power input (e.g. 2*data_width for an I**2 + Q**2 value); sizes the internal Log2 core and hence the dB dynamic range covered. |
| `out_frac` | `4` | int | Fractional bits of the dB output (resolution = 2**-out_frac dB). More bits widen the constant-scale multiplier and the output word accordingly. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_logdb.py` (bit-exact/SNR under randomized backpressure).
