# Clock-domain crossing

`LiteDSPIQClockDomainCrossing` — `litedsp.stream.adapt` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Cross an I/Q stream between clock domains via a LiteX async FIFO.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `cd_from` | `"sys"` | str | Clock-domain name of the ``sink`` (producer) side, e.g. "sys" or "adc". |
| `cd_to` | `"sys"` | str | Clock-domain name of the ``source`` (consumer) side. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `depth` | `8` | int | Async FIFO depth in samples; deeper absorbs more rate jitter between the domains at the cost of buffer registers/RAM. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_adapt.py` (bit-exact/SNR under randomized backpressure).
