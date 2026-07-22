# AN007 — AIS GMSK receiver

Runnable example: [`examples/ais_receiver.py`](../../examples/ais_receiver.py).

## Objective and chain

Exercise the receive-side core of an AIS modem at 9600 baud and four samples/symbol:

```
BT=0.4 GMSK + CFO + AWGN -> LiteDSPFMDemod -> remove CFO -> integrate/dump
                                             -> NRZI decode -> 24-bit training -> payload/FCS
```

AIS uses continuous-phase GMSK and HDLC-style NRZI, where a zero causes a transition. The
example shapes the transmitted frequency pulse with a unit-area BT=0.4 Gaussian, applies the
MSK ±π/2 phase change per symbol, adds an LO error and noise, then streams the quantized I/Q
through the actual CORDIC-based RTL FM discriminator. Host-side integrate/dump and NRZI logic
stand in for a future complete AIS framer.

## Golden checks

The script finds the 24-bit alternating training sequence at the exact symbol, recovers a
96-bit payload and 16-bit X.25 FCS with zero errors, validates the FCS, and gates the minimum
decision eye. Timing is ideal in this note; insert `LiteDSPTimingRecovery(detector="gardner")`
for a free-running front end and use `LiteDSPFrameSync` for a packaged streaming frame marker.

```sh
python3 examples/ais_receiver.py
python3 -m unittest test.test_examples.TestAppNoteExamples.test_ais_receiver_smoke -v
```

Cross-links: [`fm_demod`](../blocks/fm_demod.md),
[`timing_recovery`](../blocks/timing_recovery.md), and [`frame_sync`](../blocks/frame_sync.md).
