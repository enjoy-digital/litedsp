# Slicer

`LiteDSPSlicer` — `litedsp.comm.slicer` — category `comm`

latency: 1 sample · CSR: no · bypass: no

## Overview

Hard-decision QAM slicer: map each of I/Q to the nearest PAM level.

``bits_per_axis`` sets ``L = 2**bits_per_axis`` levels per axis at positions
``(2k-(L-1))*spacing``. Emits the decided constellation point on ``source`` (I/Q) and the
symbol index on ``source.symbol`` (``[q_bits | i_bits]``). QPSK = ``bits_per_axis=1``,
16-QAM = ``2``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `bits_per_axis` | `1` | int | Bits decided per I/Q axis: L = 2**bits_per_axis PAM levels per axis (1 = QPSK, 2 = 16-QAM); comparator count grows as L-1 per axis. |
| `spacing` | `8192` | int | Half the distance between adjacent PAM levels, in input LSBs; levels sit at (2k-(L-1))*spacing and decision boundaries at even multiples of spacing. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_slicer.py` (bit-exact/SNR under randomized backpressure).
