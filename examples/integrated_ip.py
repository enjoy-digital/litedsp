#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Preview of the integratable IP-core target (the goal of litedsp/flow/, Part C of the plan).

It assembles a small chain (DC-blocker -> gain -> framer), exposes the head/tail as
``AXIStreamInterface`` data ports, and shows the two pieces the flow-graph generator will produce
automatically:

  1. The **CSR register map** — built for free by ``get_csrs()``, which recursively gathers and
     name-prefixes every sub-block's CSRs (this is why the generator does not hand-maintain a map).
  2. The **chain Verilog** with AXI-Stream ports — emitted via ``litedsp.verilog``.

The full version (Part C, Phase 2) wraps this in a LiteX ``SoCMini`` + ``Builder`` to also emit
the AXI-Lite<->CSR bridge and csr.csv / csr.json / csr.h. Here the AXI-Lite side is left as the
documented next step.

Run ``python3 examples/integrated_ip.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litex.gen import LiteXModule

from litex.soc.interconnect.axi import AXIStreamInterface

from litedsp.common            import iq_layout
from litedsp.filter.dc_blocker import DCBlocker
from litedsp.level.gain        import Gain
from litedsp.stream.framing    import StreamFramer

from litedsp.verilog import to_verilog

# IP chain -----------------------------------------------------------------------------------------

class IPChain(LiteXModule):
    """DC-blocker -> Gain -> Framer, with AXI-Stream data ports."""
    def __init__(self, data_width=16, frame_len=256, with_csr=True):
        self.axis_sink   = AXIStreamInterface(layout=iq_layout(data_width))
        self.axis_source = AXIStreamInterface(layout=iq_layout(data_width))

        self.dcblock = DCBlocker(data_width=data_width, with_csr=with_csr)
        self.gain    = Gain(data_width=data_width, with_csr=with_csr)
        self.framer  = StreamFramer(length=frame_len, data_width=data_width, with_csr=with_csr)

        # AXI-Stream carries extra param fields (id/dest/user/keep) the DSP endpoints don't use.
        axi_only = {"id", "dest", "user", "keep"}
        self.comb += [
            self.axis_sink.connect(self.dcblock.sink, omit=axi_only),
            self.dcblock.source.connect(self.gain.sink),
            self.gain.source.connect(self.framer.sink),
            self.framer.source.connect(self.axis_source, omit=axi_only),
        ]

# Demo ---------------------------------------------------------------------------------------------

def main():
    # 1) Register map (what the generator would emit as csr.csv / csr.json / csr.h).
    chain = IPChain(with_csr=True)
    csrs  = chain.get_csrs()
    print("Aggregated CSR register map (auto-prefixed by sub-block):")
    for csr in csrs:
        print(f"  {csr.name:<24} {csr.size:>3} bits")
    assert any(c.name.startswith("gain") for c in csrs)
    assert any(c.name.startswith("framer") for c in csrs)

    # 2) Chain Verilog with AXI-Stream ports.
    ip   = IPChain(with_csr=False)
    ios  = set(ip.axis_sink.flatten()) | set(ip.axis_source.flatten())
    ios |= {ip.gain.gain, ip.gain.shift, ip.gain.bypass, ip.framer.length}
    build_dir = os.path.join(os.path.dirname(__file__), "build", "integrated_ip")
    path = to_verilog(ip, ios, "litedsp_ip", build_dir)
    print(f"\nGenerated chain Verilog: {path}")
    assert os.path.exists(path)
    print("  PASS: chain assembled with AXI-Stream ports; CSR map aggregated via get_csrs()")
    print("  Next (Part C Phase 2): wrap in SoCMini+Builder for the AXI-Lite<->CSR bridge + headers")

if __name__ == "__main__":
    main()
