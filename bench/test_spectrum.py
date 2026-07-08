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

# Helpers ------------------------------------------------------------------------------------------

def phase_inc(freq, clk_freq, phase_bits=32):
    return int(freq/clk_freq * 2**phase_bits) & (2**phase_bits - 1)

def to_signed16(v):
    return v - 0x10000 if v & 0x8000 else v

def read_capture(bus, depth):
    samples = np.zeros(depth, dtype=complex)
    for k in range(depth):
        word = bus.regs.reader_data.read()
        samples[k] = complex(to_signed16(word & 0xFFFF), to_signed16((word >> 16) & 0xFFFF))
        bus.regs.reader_pop.write(1)
    return samples

def ascii_spectrum(psd_db, width=64, height=16):
    bins = np.array_split(psd_db, width)
    cols = np.array([b.max() for b in bins])
    lo, hi = cols.min(), cols.max()
    rows = []
    for level in np.linspace(hi, lo, height):
        rows.append("".join("#" if c >= level else " " for c in cols))
    return "\n".join(rows)

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
    bus.regs.nco_phase_inc.write(phase_inc(args.tone_freq, clk_freq))
    bus.regs.ddc_nco_phase_inc.write(phase_inc(-args.tune_freq, clk_freq))

    # Trigger a capture and drain the buffer.
    bus.regs.capture_force.write(0)
    bus.regs.capture_force.write(1)
    samples = read_capture(bus, depth)
    bus.regs.capture_force.write(0)

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
