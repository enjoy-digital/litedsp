# Noise (AWGN)

`LiteDSPNoiseSource` — `litedsp.generation.source` — category `generation`

latency: variable (data-dependent) · CSR: no · bypass: no

## Overview

Approximate-Gaussian (AWGN) complex noise via summed xorshift32 streams (CLT).

``n_sum`` independent xorshift32 PRNGs per axis; their signed top bits are summed and scaled
so the output approaches a normal distribution (Irwin-Hall). For BER/AWGN testbenches.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_sum` | `16` | int | Independent xorshift32 streams summed per axis (>= 1); larger values make the distribution more Gaussian at the cost of one 32-bit PRNG each (registers + XORs). |
| `shift` | `2` | int | Output rescale shift (defaults to data_width - 1). |
| `seed` | `19088743` | int | Base seed from which every PRNG's initial state is derived; the noise sequence is deterministic and reproducible for a given seed. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_source.py` (bit-exact/SNR under randomized backpressure).
