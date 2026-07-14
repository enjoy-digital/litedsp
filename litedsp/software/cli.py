#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSP host CLI over litex_server: inspect and control blocks in a running SoC.

Run ``litex_server`` against the target (UART/Ethernet/PCIe bridge), then::

    litedsp_cli info                          # Discover LiteDSP blocks in the SoC.
    litedsp_cli nco nco --freq 1e6            # Tune an NCO (Hz).
    litedsp_cli nco ddc_nco --freq -1e6       # Tune the DDC LO.
    litedsp_cli capture --samples 1024        # Trigger + drain a capture to stats/.npy.
    litedsp_cli spectrum --sample-rate 12.5e6 # Capture + ASCII PSD.
"""

import argparse

from litedsp.software.drivers import discover, NCODriver, CaptureDriver, CSRReaderDriver

# Helpers ------------------------------------------------------------------------------------------

def _connect(args):
    from litex import RemoteClient
    bus = RemoteClient(csr_csv=args.csr_csv)
    bus.open()
    clk_freq = getattr(bus.constants, "config_clock_frequency", None)
    return bus, clk_freq

def _get(blocks, cls, prefix=None, what=""):
    matches = {p: d for p, d in blocks.items() if isinstance(d, cls)
               and (prefix is None or p == prefix)}
    if len(matches) != 1:
        raise SystemExit(f"specify one {what} among: {', '.join(sorted(matches)) or 'none found'}")
    return next(iter(matches.values()))

def _capture_samples(blocks, args):
    capture = _get(blocks, CaptureDriver,   args.capture, "capture block (--capture)")
    reader  = _get(blocks, CSRReaderDriver, args.reader,  "reader block (--reader)")
    capture.trigger()
    return _np().array(reader.read_samples(args.samples))

def _np():
    import numpy as np
    return np

def ascii_spectrum(psd_db, width=64, height=16):
    np   = _np()
    cols = np.array([b.max() for b in np.array_split(psd_db, width)])
    lo, hi = cols.min(), cols.max()
    lines  = []
    for level in np.linspace(hi, lo, height):
        lines.append("".join("#" if c >= level else " " for c in cols))
    return "\n".join(lines)

# Commands -----------------------------------------------------------------------------------------

def cmd_info(args):
    bus, clk_freq = _connect(args)
    ident = getattr(bus.constants, "config_ident", "?")
    print(f"SoC: {ident} (clk={clk_freq/1e6 if clk_freq else '?'} MHz)")
    for prefix, driver in sorted(discover(bus, clk_freq).items()):
        print(f"  {prefix:24s} {type(driver).__name__}")
    bus.close()

def cmd_nco(args):
    bus, clk_freq = _connect(args)
    nco = NCODriver(bus, args.prefix, clk_freq=clk_freq)
    if args.freq is not None:
        nco.set_frequency(args.freq)
    print(f"{args.prefix}: {nco.get_frequency()/1e6:.6f} MHz")
    bus.close()

def cmd_capture(args):
    bus, clk_freq = _connect(args)
    samples = _capture_samples(discover(bus, clk_freq), args)
    np = _np()
    print(f"captured {len(samples)} samples: "
          f"mean={samples.mean():.1f}, rms={np.sqrt((abs(samples)**2).mean()):.1f}, "
          f"peak={abs(samples).max():.0f}")
    if args.npy:
        np.save(args.npy, samples)
        print(f"saved to {args.npy}")
    bus.close()

def cmd_spectrum(args):
    bus, clk_freq = _connect(args)
    samples = _capture_samples(discover(bus, clk_freq), args)
    np   = _np()
    win  = np.hanning(len(samples))
    psd  = 20*np.log10(np.abs(np.fft.fftshift(np.fft.fft(samples*win))) + 1e-9)
    fs   = args.sample_rate
    print(ascii_spectrum(psd))
    peak = np.argmax(psd)
    if fs:
        freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), 1/fs))
        print(f"peak: {freqs[peak]/1e3:.1f} kHz (fs={fs/1e6:.3f} MHz)")
    else:
        print(f"peak: bin {peak - len(samples)//2} of [{-len(samples)//2}, {len(samples)//2})")
    bus.close()

# CLI ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteDSP host CLI (over litex_server).")
    parser.add_argument("--csr-csv", default="csr.csv", help="CSR map exported at build time.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Discover LiteDSP blocks in the SoC.")

    p = sub.add_parser("nco", help="Read/tune an NCO.")
    p.add_argument("prefix",                            help="NCO register prefix (e.g. nco, ddc_nco).")
    p.add_argument("--freq", default=None, type=float,  help="Frequency to set (Hz, signed).")

    for name, help_ in [("capture", "Trigger + drain a capture buffer."),
                        ("spectrum", "Capture + ASCII PSD.")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--capture", default=None,             help="Capture block prefix (if several).")
        p.add_argument("--reader",  default=None,             help="CSRReader block prefix (if several).")
        p.add_argument("--samples", default=1024, type=int,   help="Samples to read.")
        if name == "capture":
            p.add_argument("--npy",         default=None,             help="Save samples to a .npy file.")
        else:
            p.add_argument("--sample-rate", default=None, type=float, help="Sample rate (Hz).")

    args = parser.parse_args()
    {"info": cmd_info, "nco": cmd_nco, "capture": cmd_capture, "spectrum": cmd_spectrum}[args.cmd](args)

if __name__ == "__main__":
    main()
