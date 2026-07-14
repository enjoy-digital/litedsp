#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-driver coverage: every CSR-bearing palette block is drivable.

Builds a mock bus from each block's own reflected CSR list (the same source the hardware
register map is generated from), then checks that manifest-driven ``discover()`` returns a
working driver for every instance — typed where one exists, generic reflected otherwise —
and that the generic field accessors read-modify-write correctly.
"""

import unittest

from litedsp.flow import registry as flow_registry

from litedsp.software.drivers import discover, make_driver, TYPED

# Mock bus -------------------------------------------------------------------------------------------

class MockCSR:
    def __init__(self):
        self.value = 0

    def read(self):
        return self.value

    def write(self, value):
        self.value = value

class MockBus:
    def __init__(self, blocks):
        """``blocks`` = {prefix: BlockSpec}: registers named <prefix>_<csr>."""
        class Regs: pass
        self.regs = Regs()
        for prefix, spec in blocks.items():
            for c in spec.csrs:
                setattr(self.regs, f"{prefix}_{c.name}", MockCSR())

class TestDriverCoverage(unittest.TestCase):
    def test_every_csr_block_drivable(self):
        palette  = flow_registry.registry()
        csrful   = {k: s for k, s in palette.items() if s.csrs}
        manifest = {f"u_{k}": k for k in csrful}
        bus      = MockBus({f"u_{k}": s for k, s in csrful.items()})
        found    = discover(bus, manifest=manifest)
        missing  = sorted(set(manifest) - set(found))
        self.assertFalse(missing, f"CSR-bearing blocks without a driver: {missing}")
        self.assertGreaterEqual(len(found), 50)

    def test_generic_field_accessors(self):
        palette = flow_registry.registry()
        spec    = palette["cic_decimator"]           # config CSR with rate/stages fields.
        bus     = MockBus({"u": spec})
        drv     = make_driver(spec)(bus, "u")
        drv.set_config_rate(12)
        drv.set_config_stages(3)
        self.assertEqual(drv.get_config_rate(), 12)
        self.assertEqual(drv.get_config_stages(), 3)
        # RMW: stages write must not clobber rate.
        drv.set_config_stages(4)
        self.assertEqual(drv.get_config_rate(), 12)

    def test_typed_preferred(self):
        palette = flow_registry.registry()
        bus     = MockBus({"n": palette["nco"]})
        found   = discover(bus, manifest={"n": "nco"})
        self.assertEqual(type(found["n"]).__name__, "NCODriver")

if __name__ == "__main__":
    unittest.main()
