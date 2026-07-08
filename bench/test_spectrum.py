#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""
Host test for the LiteDSP spectrum bench: tune, capture, PSD, check the tone bin.

Run ``litex_server --uart --uart-port=/dev/ttyUSB0`` against a board loaded with
``bench/spectrum.py``, then::

    python3 bench/test_spectrum.py --tone-freq=1e6 --tune-freq=1e6

The test tone is generated on-chip (NCO), mixed with AWGN, down-converted by ``tune-freq``
and decimated; the captured baseband buffer is read back and its PSD peak is checked against
the expected offset ``tone-freq - tune-freq``. An ASCII spectrum is printed.
"""

import argparse

import numpy as np

from litex import RemoteClient

from litedsp.software.drivers import NCODriver, CaptureDriver, CSRReaderDriver
from litedsp.software.cli     import ascii_spectrum

# Test ---------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteDSP spectrum bench host test.")
    parser.add_argument("--tone-freq", default=1e6,  type=float, help="On-chip test tone frequency (Hz).")
    parser.add_argument("--tune-freq", default=1e6,  type=float, help="DDC tune frequency (Hz).")
    parser.add_argument("--csr-csv",   default="csr.csv",        help="CSR map exported at build time.")
    args = parser.parse_args()

    bus = RemoteClient(csr_csv=args.csr_csv)
    bus.open()

    clk_freq   = bus.constants.config_clock_frequency
    depth      = bus.constants.spectrum_capture_depth
    decimation = bus.constants.spectrum_decimation
    fs_bb      = clk_freq/decimation
    print(f"{bus.constants.config_ident}: clk={clk_freq/1e6:.1f}MHz, capture={depth}, fs_bb={fs_bb/1e6:.3f}MHz")

    # Tune: test tone at +tone_freq, DDC LO at -tune_freq (down-conversion).
    tone = NCODriver(bus, "nco",     clk_freq=clk_freq)
    lo   = NCODriver(bus, "ddc_nco", clk_freq=clk_freq)
    tone.set_frequency(args.tone_freq)
    lo.set_frequency(-args.tune_freq)

    # Trigger a capture and drain the buffer.
    capture = CaptureDriver(bus, "capture")
    reader  = CSRReaderDriver(bus, "reader")
    capture.trigger()
    samples = np.array(reader.read_samples(depth))

    # PSD + peak check.
    win  = np.hanning(depth)
    spec = np.fft.fftshift(np.fft.fft(samples*win))
    psd  = 20*np.log10(np.abs(spec) + 1e-9)
    freqs = np.fft.fftshift(np.fft.fftfreq(depth, 1/fs_bb))

    peak     = freqs[np.argmax(psd)]
    expected = args.tone_freq - args.tune_freq
    bin_hz   = fs_bb/depth
    print(ascii_spectrum(psd))
    print(f"peak at {peak/1e3:.1f} kHz, expected {expected/1e3:.1f} kHz (bin = {bin_hz/1e3:.2f} kHz)")

    bus.close()
    if abs(peak - expected) <= 2*bin_hz:
        print("PASS")
        return 0
    print("FAIL")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
