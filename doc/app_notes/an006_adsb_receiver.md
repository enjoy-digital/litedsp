# AN006 — ADS-B / Mode-S receiver

Runnable example: [`examples/adsb_receiver.py`](../../examples/adsb_receiver.py).

## Objective and chain

Acquire an ADS-B extended squitter at the standard 2 MHz minimum sample rate, then decode its
112 pulse-position-modulated bits:

```
2 MHz magnitude samples -> LiteDSPCorrelator(8 us preamble) -> frame start
                                                    -> compare early/late half-bit -> 112 bits
```

The Mode-S preamble pulses occur at 0, 1, 3.5 and 4.5 us, or sample positions 0, 2, 7 and 9.
The example uses a zero-mean 16-sample matched template, so DC/noise-floor energy is rejected.
The correlator is actual RTL; only the post-acquisition PPM early/late comparison is host-side.

## Golden checks

The deterministic stimulus contains a DF17 prefix, AWGN, a 24-sample arrival offset and a full
112-bit payload. The script requires exact preamble position, zero decoded bit errors, the DF17
prefix, and at least 3 dB peak-to-sidelobe correlation margin. On hardware, place magnitude or
power detection before the correlator and use the detected sample index to arm `LiteDSPCapture`.

```sh
python3 examples/adsb_receiver.py
python3 -m unittest test.test_examples.TestAppNoteExamples.test_adsb_receiver_smoke -v
```

Cross-links: [`correlator`](../blocks/correlator.md), [`magnitude`](../blocks/magnitude.md),
[`capture`](../blocks/capture.md), and [`timestamper`](../blocks/timestamper.md).
