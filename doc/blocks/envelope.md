# Envelope detector

`LiteDSPEnvelopeDetector` — `litedsp.level.peak` — category `level`

latency: 2 samples · CSR: no · bypass: no

## Overview

Envelope follower on |I+jQ| with separate attack/release time constants.

``env += (|x| - env) >> attack`` when rising, ``>> release`` when falling (single-pole
smoothing; larger shift = slower). With ``release`` very large it approximates peak-hold.
Magnitude uses the alpha-max-beta-min approximation.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `attack` | `2` | int | Attack shift, applied while the magnitude rises (env += (|x| - env) >> attack). Smaller = faster tracking of level increases; time constant ~ 2**attack samples. |
| `release` | `6` | int | Release shift, applied while the magnitude falls; larger = slower decay (time constant ~ 2**release samples). A very large value approximates a peak-hold detector. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_peak.py` (bit-exact/SNR under randomized backpressure).
