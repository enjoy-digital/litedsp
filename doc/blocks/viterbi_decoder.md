# Viterbi decoder

`LiteDSPViterbiDecoder` — `litedsp.comm.viterbi` — category `comm`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Hard-decision Viterbi decoder (rate 1/n, register-exchange survivors).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `constraint` | `7` | int | Constraint length K, matching the encoder's; the fully-parallel ACS spans 2**(K-1) states, so resources grow exponentially with K. |
| `polys` | `(121, 91)` | list | Generator polynomials, octal, matching the encoder's (rate 1/len(polys); default (0o171, 0o133): the CCSDS/Voyager K=7 pair). |
| `traceback` | — | none | Register-exchange survivor depth in symbols = decoding delay (default 8*K, well past the ~5K convergence rule of thumb); each state keeps a traceback-bit register. |
| `metric_width` | `10` | int | Path-metric register width in bits; metrics are min-normalized each step, so it only needs headroom for the metric spread plus branch adds. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `constraint` | `0` | Constraint length K. |
| `[23:8]` | `traceback` | `0` | Survivor depth (decoding delay). |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_viterbi.py` (bit-exact/SNR under randomized backpressure).
