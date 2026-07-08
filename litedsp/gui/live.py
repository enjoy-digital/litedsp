#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Live session: connect the flow editor to a running SoC over litex_server.

Pure logic (no DearPyGui): opens a ``RemoteClient`` on the SoC's ``csr.csv``, auto-discovers
LiteDSP blocks via :func:`litedsp.software.drivers.discover` and exposes the runtime controls
the GUI binds widgets to (NCO tuning, FIR reload, capture + PSD). In a FlowChain/FlowIPCore SoC
the discovered prefixes are the netlist block ids, so live controls line up with editor nodes.
Testable headless by injecting any bus with ``regs``/``constants``.
"""

from litedsp.software.drivers import discover, NCODriver, CaptureDriver, CSRReaderDriver, FIRDriver

# Live Session -------------------------------------------------------------------------------------

class LiveSession:
    def __init__(self, csr_csv="csr.csv", bus=None):
        self.csr_csv  = csr_csv
        self.bus      = bus
        self.blocks   = {}
        self.clk_freq = None

    def open(self):
        """Connect and discover; returns ``{prefix: driver}``."""
        if self.bus is None:
            from litex import RemoteClient
            self.bus = RemoteClient(csr_csv=self.csr_csv)
        if hasattr(self.bus, "open"):
            self.bus.open()
        self.clk_freq = getattr(getattr(self.bus, "constants", None), "config_clock_frequency", None)
        self.blocks   = discover(self.bus, clk_freq=self.clk_freq)
        return self.blocks

    def close(self):
        if self.bus is not None and hasattr(self.bus, "close"):
            self.bus.close()
        self.bus, self.blocks = None, {}

    # Typed views over the discovered blocks.
    def of_type(self, cls):
        return {p: d for p, d in self.blocks.items() if isinstance(d, cls)}

    @property
    def ncos(self):     return self.of_type(NCODriver)
    @property
    def firs(self):     return self.of_type(FIRDriver)
    @property
    def captures(self): return self.of_type(CaptureDriver)
    @property
    def readers(self):  return self.of_type(CSRReaderDriver)

    # Runtime operations the GUI binds to.
    def tune(self, prefix, freq):
        self.blocks[prefix].set_frequency(freq)

    def load_taps(self, prefix, taps):
        self.blocks[prefix].load(taps)

    def capture_psd(self, capture, reader, n=1024):
        """Trigger ``capture``, drain ``n`` samples from ``reader``, return (freq_norm, psd_db)."""
        import numpy as np
        self.blocks[capture].trigger()
        samples = np.array(self.blocks[reader].read_samples(n))
        win  = np.hanning(len(samples))
        psd  = 20*np.log10(np.abs(np.fft.fftshift(np.fft.fft(samples*win))) + 1e-9)
        freq = np.fft.fftshift(np.fft.fftfreq(len(samples)))
        return freq, psd
