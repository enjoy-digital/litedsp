# AM demod

`LiteDSPAMDemod` — `litedsp.comm.am_demod` — category `comm`

latency: 2 samples · CSR: no · bypass: no

## Overview

AM envelope demodulator: ``|x|`` (magnitude) with the carrier DC removed.

A :class:`LiteDSPMagnitude` followed by a multiplier-free 1st-order DC blocker (pole
``1 - 2**-pole_shift``). Output is the recovered modulating signal (signed).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `pole_shift` | `8` | int | DC-blocker pole position: pole = 1 - 2**-pole_shift. Larger values lower the high-pass cutoff (slower carrier-DC settling); implemented as a shift, no multiplier. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
