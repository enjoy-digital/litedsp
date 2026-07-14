#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""
LiteDSP spectrum bench: tone + AWGN -> DDC -> Capture, controlled over UARTBone.

Proves the generation/mixing/rate/capture path on real hardware with nothing but a serial
cable: the host tunes the test tone and the DDC LO, force-triggers a capture and drains the
I/Q buffer back over the bridge (see ``bench/test_spectrum.py``, which computes the PSD and
checks the tone lands in the expected bin).

Build/load (Arty):       python3 bench/spectrum.py --board=arty --build --load
Build/load (Colorlight): python3 bench/spectrum.py --board=colorlight_5a_75b --build --load
Host test:               litex_server --uart --uart-port=/dev/ttyUSB0
                         python3 bench/test_spectrum.py --tone-freq=1e6
"""

import argparse
import importlib

from migen import *

from litex.gen import *

from litex.soc.integration.soc      import SoCRegion
from litex.soc.integration.soc_core import SoCMini
from litex.soc.integration.builder  import Builder
from litex.soc.cores.led            import LedChaser

from litedsp.generation.nco    import LiteDSPNCO
from litedsp.generation.source import LiteDSPNoiseSource
from litedsp.stream.ops        import LiteDSPIQAdd
from litedsp.mixing.ddc        import LiteDSPDDC
from litedsp.stream.capture    import LiteDSPCapture
from litedsp.stream.csr_io     import LiteDSPCSRReader

# Boards -------------------------------------------------------------------------------------------

BOARDS = {
    "arty" : dict(
        platform     = "litex_boards.platforms.digilent_arty",
        target       = "litex_boards.targets.digilent_arty",
        crg_kwargs   = {"with_dram": False},
        sys_clk_freq = int(100e6),
        with_leds    = True,
    ),
    "colorlight_5a_75b" : dict(
        platform     = "litex_boards.platforms.colorlight_5a_75b",
        target       = "litex_boards.targets.colorlight_5a_75x",
        crg_kwargs   = {"with_rst": False},   # Button shares its pin with serial RX (UARTBone).
        sys_clk_freq = int(60e6),
        with_leds    = False,                 # LED shares its pin with serial TX (UARTBone).
    ),
}

# Bench SoC ----------------------------------------------------------------------------------------

class BenchSoC(SoCMini):
    def __init__(self, board="arty", sys_clk_freq=None, capture_depth=2048):
        cfg          = BOARDS[board]
        platform     = importlib.import_module(cfg["platform"]).Platform()
        target       = importlib.import_module(cfg["target"])
        sys_clk_freq = int(sys_clk_freq or cfg["sys_clk_freq"])

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, clk_freq=sys_clk_freq,
            ident         = f"LiteDSP spectrum bench on {board}",
            ident_version = True,
        )

        # CRG --------------------------------------------------------------------------------------
        self.crg = target._CRG(platform, sys_clk_freq, **cfg["crg_kwargs"])

        # UARTBone (host bridge) ---------------------------------------------------------------
        self.add_uartbone()

        # DSP chain: tone + noise -> DDC -> capture -> CSR readout ----------------------------------
        self.nco     = LiteDSPNCO(data_width=16)                     # Test tone (phase_inc CSR).
        self.noise   = LiteDSPNoiseSource(data_width=16, shift=4)    # AWGN floor.
        self.adder   = LiteDSPIQAdd(data_width=16)
        self.ddc     = LiteDSPDDC(data_width=16, decimation=8)       # Tune (nco phase_inc) + /8.
        self.capture = LiteDSPCapture(depth=capture_depth, data_width=16, with_wishbone=True)
        self.reader  = LiteDSPCSRReader(data_width=16)
        # Fast readout: the capture buffer as a memory-mapped window (one sample per word).
        self.bus.add_slave(name="capture_mem", slave=self.capture.bus,
            region=SoCRegion(origin=0x3000_0000, size=self.capture.mem_size, cached=False))
        self.comb += [
            self.nco.source.connect(self.adder.sink_a),
            self.noise.source.connect(self.adder.sink_b),
            self.adder.source.connect(self.ddc.sink),
            self.ddc.source.connect(self.capture.sink),
            self.capture.source.connect(self.reader.sink),
        ]
        self.add_constant("SPECTRUM_CAPTURE_DEPTH", capture_depth)
        self.add_constant("SPECTRUM_DECIMATION",    8)

        # Leds (sign of life) ------------------------------------------------------------------
        if cfg["with_leds"]:
            self.leds = LedChaser(pads=platform.request_all("user_led"), sys_clk_freq=sys_clk_freq)

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteDSP spectrum bench.")
    parser.add_argument("--board",         default="arty",            choices=sorted(BOARDS.keys()), help="Target board.")
    parser.add_argument("--build",         action="store_true",       help="Build the bitstream.")
    parser.add_argument("--load",          action="store_true",       help="Load the bitstream.")
    parser.add_argument("--sys-clk-freq",  default=None, type=float,  help="System clock frequency.")
    parser.add_argument("--capture-depth", default=2048, type=int,    help="Capture buffer depth (samples).")
    args = parser.parse_args()

    soc     = BenchSoC(board=args.board, sys_clk_freq=args.sys_clk_freq,
        capture_depth=args.capture_depth)
    builder = Builder(soc, csr_csv="csr.csv")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))

if __name__ == "__main__":
    main()
