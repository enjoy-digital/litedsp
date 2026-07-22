# AN006 — ADS-B / Mode-S receiver

Runnable example: [`examples/adsb_receiver.py`](../../examples/adsb_receiver.py).

## Objective and chain

Acquire an ADS-B extended squitter at the standard 2 MHz minimum sample rate, decode its
112 pulse-position-modulated bits, parse the DF17 header, and validate Mode-S CRC-24:

```
2 MHz magnitude samples -> LiteDSPCorrelator(8 us preamble) -> frame start
                                                    -> compare early/late half-bit -> 112 bits
                                                    -> DF/CA/ICAO/ME parse -> CRC-24
```

The Mode-S preamble pulses occur at 0, 1, 3.5 and 4.5 us, or sample positions 0, 2, 7 and 9.
The example uses a zero-mean 16-sample matched template, so DC/noise-floor energy is rejected.
The correlator is actual RTL; only the post-acquisition PPM early/late comparison is host-side.

## Golden checks

The deterministic stimulus is a standards-shaped long Mode-S frame: DF17, CA=5, ICAO address
`A5C33C`, a type-code 11 airborne-position ME field, and the 24-bit remainder of generator
`0x1FFF409`. The script requires exact preamble position, zero decoded bit errors, exact field
values, a zero CRC syndrome, rejection after a deliberate one-bit corruption, and at least 3 dB
peak-to-sidelobe margin. On hardware, place magnitude or power detection before the correlator
and use the detected sample index to arm `LiteDSPCapture`.

```sh
python3 examples/adsb_receiver.py
python3 -m unittest test.test_examples.TestAppNoteExamples.test_adsb_receiver_smoke -v
```

Cross-links: [`correlator`](../blocks/correlator.md), [`magnitude`](../blocks/magnitude.md),
[`capture`](../blocks/capture.md), and [`timestamper`](../blocks/timestamper.md).
