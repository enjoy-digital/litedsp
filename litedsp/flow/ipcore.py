#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Wrap an assembled chain as an integratable IP core: AXI-Stream data + AXI-Lite config.

``FlowIPCore`` takes a netlist, builds the :class:`~litedsp.flow.builder.FlowChain` with CSRs, and
adds an AXI-Lite -> CSR bridge over a :class:`~litex.soc.interconnect.csr_bus.CSRBankArray` (one
bank per block, addressed exactly as LiteX/SoCMini would). The chain's top-level stream endpoints
are already AXI-Stream-compatible (``valid``=tvalid, ``ready``=tready, ``last``=tlast,
``payload_i``/``payload_q``=tdata), so they are exposed directly as the data ports.

``generate_ip()`` emits the Verilog plus the register map (``csr.csv`` / ``csr.json`` / ``csr.h``)
— the artifacts needed to drop the core into a LiteX/Vivado design and drive it from software.
"""

import os

from migen import *

from litex.gen import *

from litex.soc.interconnect      import csr_bus
from litex.soc.interconnect.axi  import AXILiteInterface, AXILite2CSR
from litex.soc.integration.soc   import SoCCSRRegion

from litedsp.flow.builder import FlowChain
from litedsp.flow import netlist as netlist_mod

_PAGING = 0x800   # Bytes per CSR bank (LiteX default; bank byte origin = index * paging).

# Standard AXI4-Lite port fields per channel (valid/ready are implicit on every channel).
_AXIL_PAYLOAD = {"aw": ["addr"], "w": ["data", "strb"], "b": ["resp"],
                 "ar": ["addr"], "r": ["data", "resp"]}

def _name_axilite(axil, prefix="s_axil"):
    """Give the AXI-Lite leaf signals canonical names (s_axil_awvalid, ...) and return them."""
    sigs = []
    for ch, payloads in _AXIL_PAYLOAD.items():
        ep = getattr(axil, ch)
        for fld, sig in (("valid", ep.valid), ("ready", ep.ready)):
            sig.name_override = f"{prefix}_{ch}{fld}"
            sigs.append(sig)
        for p in payloads:
            sig = getattr(ep, p)
            sig.name_override = f"{prefix}_{ch}{p}"
            sigs.append(sig)
    return sigs

# IP core ------------------------------------------------------------------------------------------

class FlowIPCore(LiteXModule):
    def __init__(self, nl, reg=None, csr_data_width=32, axil_address_width=16, csr_base=0):
        assert csr_data_width == 32
        self.netlist            = nl
        self.csr_data_width     = csr_data_width
        self.csr_base           = csr_base
        self.axil_address_width = axil_address_width

        # Chain (CSRs enabled) -- its top endpoints are the AXI-Stream data ports.
        self.chain = FlowChain(nl, reg=reg, with_csr=True)

        # AXI-Lite -> CSR bus -> one CSR bank per block.
        self.axil    = AXILiteInterface(data_width=csr_data_width, address_width=axil_address_width)
        self.csrbus  = csr_bus.Interface(data_width=csr_data_width,
            address_width=axil_address_width - 2)            # AXI is byte-addressed; CSR is word.
        self.axil2csr = AXILite2CSR(self.axil, self.csrbus)
        self._bank_index = {}
        self.csrbankarray = csr_bus.CSRBankArray(self.chain, self._bank_addr,
            data_width=csr_data_width, address_width=axil_address_width - 2, paging=_PAGING)
        self.csr_interconnect = csr_bus.Interconnect(self.csrbus, self.csrbankarray.get_buses())

    def _bank_addr(self, name, memory):
        if memory is not None:
            return None
        return self._bank_index.setdefault(name, len(self._bank_index))

    # Register map -------------------------------------------------------------------------------
    def csr_regions(self):
        regions = {}
        for name, csrs, mapaddr, rmap in self.csrbankarray.banks:
            origin = self.csr_base + mapaddr*_PAGING
            regions[name] = SoCCSRRegion(origin, self.csr_data_width, csrs)
        return regions

    def export_csv(self):
        from litex.soc.integration.export import get_csr_csv
        return get_csr_csv(csr_regions=self.csr_regions())

    def export_json(self):
        from litex.soc.integration.export import get_csr_json
        return get_csr_json(csr_regions=self.csr_regions())

    def export_header(self):
        from litex.soc.integration.export import get_csr_header
        return get_csr_header(regions=self.csr_regions(), constants={})

    # IO signals for Verilog generation ----------------------------------------------------------
    def io_signals(self):
        return self.chain.io_signals() | set(_name_axilite(self.axil))

# Generation ---------------------------------------------------------------------------------------

def generate_ip(source, build_dir, name=None):
    """Emit the IP Verilog + register map (csv/json/h) into ``build_dir``. Returns ``(path, ip)``."""
    from litedsp.flow.generate import emit_verilog
    nl   = source if isinstance(source, netlist_mod.Netlist) else netlist_mod.load(source)
    ip   = FlowIPCore(nl)
    name = name or (nl.name + "_ip")
    os.makedirs(build_dir, exist_ok=True)
    path = emit_verilog(ip, ip.io_signals(), name, build_dir)   # chdir so .init files land here.
    with open(os.path.join(build_dir, "csr.csv"),  "w") as f: f.write(ip.export_csv())
    with open(os.path.join(build_dir, "csr.json"), "w") as f: f.write(ip.export_json())
    with open(os.path.join(build_dir, "csr.h"),    "w") as f: f.write(ip.export_header())
    return path, ip
