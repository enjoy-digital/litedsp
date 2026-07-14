#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""
LiteDSP streaming bench: tone + AWGN -> DDC -> I/Q over UDP, control over Etherbone.

The fast-path proof point on the Colorlight 5A-75B's on-board Gigabit Ethernet: the DDC
output streams continuously to the host as fixed-size UDP sample packets (UDPIQStreamer)
while the same link carries Etherbone for CSR control (tune the tone / the DDC LO at runtime).
``bench/test_stream.py`` receives the packets and checks the live PSD.

Build/load: python3 bench/stream.py --build --load
Host:       litex_server --udp --udp-ip=192.168.1.50 &
            python3 bench/test_stream.py --tone-freq=1e6 --tune-freq=1e6
"""

import argparse

from migen import *

from litex.gen import *

from litex.soc.integration.soc_core import SoCMini
from litex.soc.integration.builder  import Builder

from litex_boards.platforms import colorlight_5a_75b
from litex_boards.targets.colorlight_5a_75x import _CRG

from litedsp.generation.nco    import LiteDSPNCO
from litedsp.generation.source import LiteDSPNoiseSource
from litedsp.stream.ops        import LiteDSPIQAdd
from litedsp.mixing.ddc        import LiteDSPDDC
from litedsp.frontend.udp      import LiteDSPUDPIQStreamer

# Bench SoC ----------------------------------------------------------------------------------------

class BenchSoC(SoCMini):
    # 40 MHz: the decimation-64 CIC's 40-bit integrator cascade closes ~48 MHz on ECP5 -6.
    def __init__(self, sys_clk_freq=int(40e6), revision="7.0",
        ip_address="192.168.1.50", host_ip="192.168.1.100", udp_port=6000,
        mac_address=0x726b895bc2e2, decimation=64, samples_per_packet=256):
        platform = colorlight_5a_75b.Platform(revision=revision)

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, clk_freq=sys_clk_freq,
            ident         = "LiteDSP streaming bench on Colorlight 5A-75B",
            ident_version = True,
        )

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq, with_rst=False)

        # Etherbone (control path) -------------------------------------------------------------
        from liteeth.phy.ecp5rgmii import LiteEthPHYRGMII
        self.ethphy = LiteEthPHYRGMII(
            clock_pads = platform.request("eth_clocks", 0),
            pads       = platform.request("eth", 0),
            tx_delay   = 0e-9)
        self.add_etherbone(phy=self.ethphy, ip_address=ip_address, mac_address=mac_address,
            data_width=32)

        # DSP chain: tone + noise -> DDC -----------------------------------------------------------
        self.nco   = LiteDSPNCO(data_width=16)                       # Test tone (phase_inc CSR).
        self.noise = LiteDSPNoiseSource(data_width=16, shift=4)      # AWGN floor.
        self.adder = LiteDSPIQAdd(data_width=16)
        self.ddc   = LiteDSPDDC(data_width=16, decimation=decimation)
        self.comb += [
            self.nco.source.connect(self.adder.sink_a),
            self.noise.source.connect(self.adder.sink_b),
            self.adder.source.connect(self.ddc.sink),
        ]

        # Data path: I/Q packets to the host over UDP (shares the Etherbone core) -------------------
        self.iq_streamer = LiteDSPUDPIQStreamer(self.ethcore_etherbone.udp,
            ip_address=host_ip, udp_port=udp_port,
            data_width=16, word_width=32, samples_per_packet=samples_per_packet)
        self.comb += self.ddc.source.connect(self.iq_streamer.sink)

        self.add_constant("STREAM_UDP_PORT",          udp_port)
        self.add_constant("STREAM_DECIMATION",        decimation)
        self.add_constant("STREAM_SAMPLES_PER_PACKET", samples_per_packet)

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteDSP streaming bench (Colorlight 5A-75B).")
    parser.add_argument("--build",    action="store_true",   help="Build the bitstream.")
    parser.add_argument("--load",     action="store_true",   help="Load the bitstream.")
    parser.add_argument("--revision", default="7.0",         help="Board revision.")
    parser.add_argument("--ip-address",   default="192.168.1.50",  help="SoC IP (Etherbone).")
    parser.add_argument("--host-ip",      default="192.168.1.100", help="Destination IP for I/Q packets.")
    args = parser.parse_args()

    soc     = BenchSoC(revision=args.revision, ip_address=args.ip_address, host_ip=args.host_ip)
    builder = Builder(soc, csr_csv="csr.csv")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(builder.get_bitstream_filename(mode="sram"))

if __name__ == "__main__":
    main()
