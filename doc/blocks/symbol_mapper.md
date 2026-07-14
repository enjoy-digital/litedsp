# Symbol mapper

`LiteDSPSymbolMapper` — `litedsp.comm.mapper` — category `comm`

latency: 1 sample · CSR: no · bypass: no

## Overview

Map a QAM symbol index to a constellation I/Q point (inverse of :class:`LiteDSPSlicer`).

``bits_per_axis`` gives ``L = 2**bits_per_axis`` PAM levels per axis at
``(2k-(L-1))*spacing``. ``sink.symbol`` is ``[q_bits | i_bits]``. QPSK = ``1``, 16-QAM = ``2``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `bits_per_axis` | `1` | int | Bits per I/Q axis: L = 2**bits_per_axis PAM levels per axis (1 = QPSK, 2 = 16-QAM); ``sink.symbol`` is 2*bits_per_axis wide. |
| `spacing` | `8192` | int | Half the distance between adjacent PAM levels, in output LSBs; levels sit at (2k-(L-1))*spacing. Keep (L-1)*spacing within the signed data_width range. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | raw |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
