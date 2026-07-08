#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""
Host test for the LiteDSP streaming bench: tune over Etherbone, receive I/Q over UDP.

Run ``litex_server --udp --udp-ip=192.168.1.50`` against a board loaded with
``bench/stream.py``, then::

    python3 bench/test_stream.py --tone-freq=1e6 --tune-freq=1e6

Tunes the on-chip tone and the DDC LO over Etherbone, receives the continuous UDP I/Q
packets, reports the sustained sample rate, and checks the PSD peak lands at
``tone-freq - tune-freq``.
"""

import time
import socket
import struct
import argparse

import numpy as np

from litex import RemoteClient

from litedsp.software.drivers import NCODriver
from litedsp.software.cli     import ascii_spectrum

def receive_samples(port, n, timeout=5.0):
    """Collect n I/Q samples from the UDP packet stream; returns (samples, seconds_elapsed)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", port))
    sock.settimeout(timeout)
    samples = []
    start = None
    while len(samples) < n:
        data, _ = sock.recvfrom(65536)
        if start is None:
            start = time.monotonic()
        words = struct.unpack(f"<{len(data)//4}I", data)
        samples += [complex(np.int16(w & 0xFFFF), np.int16((w >> 16) & 0xFFFF)) for w in words]
    sock.close()
    return np.array(samples[:n]), time.monotonic() - start

def main():
    parser = argparse.ArgumentParser(description="LiteDSP streaming bench host test.")
    parser.add_argument("--tone-freq", default=1e6, type=float, help="On-chip test tone (Hz).")
    parser.add_argument("--tune-freq", default=1e6, type=float, help="DDC tune frequency (Hz).")
    parser.add_argument("--samples",   default=65536, type=int, help="Samples to collect.")
    parser.add_argument("--csr-csv",   default="csr.csv",       help="CSR map from the build.")
    args = parser.parse_args()

    bus = RemoteClient(csr_csv=args.csr_csv)
    bus.open()
    clk_freq   = bus.constants.config_clock_frequency
    decimation = bus.constants.stream_decimation
    udp_port   = bus.constants.stream_udp_port
    fs_bb      = clk_freq/decimation
    print(f"{bus.constants.config_ident}: fs_bb={fs_bb/1e6:.3f} MHz, UDP port {udp_port}")

    # Tune over Etherbone while the stream runs.
    NCODriver(bus, "nco",     clk_freq=clk_freq).set_frequency(args.tone_freq)
    NCODriver(bus, "ddc_nco", clk_freq=clk_freq).set_frequency(-args.tune_freq)
    bus.close()

    samples, elapsed = receive_samples(udp_port, args.samples)
    rate = len(samples)/elapsed if elapsed else float("inf")
    print(f"received {len(samples)} samples at {rate/1e6:.2f} MS/s "
          f"({rate/fs_bb*100:.0f}% of fs_bb)")

    win   = np.hanning(len(samples))
    psd   = 20*np.log10(np.abs(np.fft.fftshift(np.fft.fft(samples*win))) + 1e-9)
    freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), 1/fs_bb))
    peak     = freqs[np.argmax(psd)]
    expected = args.tone_freq - args.tune_freq
    bin_hz   = fs_bb/len(samples)
    print(ascii_spectrum(psd))
    print(f"peak at {peak/1e3:.1f} kHz, expected {expected/1e3:.1f} kHz")
    if abs(peak - expected) <= 16*bin_hz:
        print("PASS")
        return 0
    print("FAIL")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
