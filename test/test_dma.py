#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for DMA capture/replay (litedsp/stream/dma.py).

The Wishbone backend is simulated against a behavioral Wishbone memory, the LiteDRAM backend
against a behavioral native-port responder; both check the full path sample stream <-> packed
memory words (Cat(i, q), first sample in the LSBs).
"""

import unittest

from migen import run_simulation, passive

from litex.soc.interconnect import wishbone

from litedsp.stream.dma import LiteDSPDMACapture, LiteDSPDMAReplay

from test.common import stream_driver, stream_capture

# Behavioral memories ------------------------------------------------------------------------------

@passive
def wb_memory(bus, mem):
    """Single-cycle-ack behavioral Wishbone slave over a {word_addr: word} dict."""
    while True:
        if (yield bus.stb) and (yield bus.cyc) and not (yield bus.ack):
            if (yield bus.we):
                mem[(yield bus.adr)] = (yield bus.dat_w)
            else:
                yield bus.dat_r.eq(mem.get((yield bus.adr), 0))
            yield bus.ack.eq(1)
        else:
            yield bus.ack.eq(0)
        yield

@passive
def dram_write_responder(port, mem):
    """Behavioral LiteDRAM native write port over a {word_addr: word} dict."""
    yield port.cmd.ready.eq(1)
    yield port.wdata.ready.eq(1)
    addrs = []
    while True:
        if (yield port.cmd.valid):
            addrs.append((yield port.cmd.addr))
        if (yield port.wdata.valid) and addrs:
            mem[addrs.pop(0)] = (yield port.wdata.data)
        yield

@passive
def dram_read_responder(port, mem):
    """Behavioral LiteDRAM native read port over a {word_addr: word} dict."""
    yield port.cmd.ready.eq(1)
    pending = []
    valid   = False
    while True:
        if valid and (yield port.rdata.ready):
            pending.pop(0)
        if (yield port.cmd.valid):
            pending.append((yield port.cmd.addr))
        valid = bool(pending)
        if valid:
            yield port.rdata.data.eq(mem.get(pending[0], 0))
        yield port.rdata.valid.eq(valid)
        yield

# Helpers ------------------------------------------------------------------------------------------

def iq_word(samples, data_width=16):
    """Pack I/Q sample tuples into one memory word (first sample in the LSBs)."""
    word = 0
    mask = (1 << data_width) - 1
    for k, (i, q) in enumerate(samples):
        word |= ((i & mask) | ((q & mask) << data_width)) << (2*data_width*k)
    return word

def wait_done(done, timeout=2000):
    for _ in range(timeout):
        if (yield done):
            return
        yield
    raise AssertionError("DMA transfer did not complete")

# Tests --------------------------------------------------------------------------------------------

class TestDMACapture(unittest.TestCase):
    def test_wishbone_capture(self):
        n    = 16
        base = 0x100
        bus  = wishbone.Interface(data_width=32)
        dut  = LiteDSPDMACapture(data_width=16, bus=bus, with_csr=False)
        dut.base.reset   = base
        dut.length.reset = n*4          # Bytes (one 32-bit word per I/Q sample).
        dut.enable.reset = 1
        samples = [{"i": 100*k + 1, "q": -(100*k + 1)} for k in range(n)]
        mem = {}
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            wb_memory(bus, mem),
            wait_done(dut.done),
        ])
        for k, s in enumerate(samples):
            self.assertEqual(mem[(base >> 2) + k], iq_word([(s["i"], s["q"])]))

    def test_dram_capture(self):
        from litedram.common import LiteDRAMNativePort
        n    = 16                        # I/Q samples; 2 per 64-bit word.
        base = 0x100
        port = LiteDRAMNativePort("write", address_width=24, data_width=64)
        dut  = LiteDSPDMACapture(data_width=16, port=port)
        dut.writer._base.storage.reset   = base
        dut.writer._length.storage.reset = n*4
        dut.writer._enable.storage.reset = 1
        samples = [{"i": 200*k + 2, "q": -(200*k + 2)} for k in range(n)]
        mem = {}
        run_simulation(dut, [
            stream_driver(dut.sink, samples, ("i", "q"), throttle=0.2),
            dram_write_responder(port, mem),
            wait_done(dut.writer._done.status),
        ])
        for k in range(n // 2):
            pair = [(samples[2*k]["i"], samples[2*k]["q"]), (samples[2*k+1]["i"], samples[2*k+1]["q"])]
            self.assertEqual(mem[(base >> 3) + k], iq_word(pair))

class TestDMAReplay(unittest.TestCase):
    def test_wishbone_replay(self):
        n    = 16
        base = 0x40
        bus  = wishbone.Interface(data_width=32)
        dut  = LiteDSPDMAReplay(data_width=16, bus=bus, with_csr=False)
        dut.base.reset   = base
        dut.length.reset = n*4
        dut.enable.reset = 1
        samples = [(300*k + 3, -(300*k + 3)) for k in range(n)]
        mem = {(base >> 2) + k: iq_word([s]) for k, s in enumerate(samples)}
        cap = []
        run_simulation(dut, [
            wb_memory(bus, mem),
            stream_capture(dut.source, cap, n, ("i", "q"), ready_rate=0.7),
        ])
        mask = 0xFFFF
        for s, c in zip(samples, cap):
            self.assertEqual((c["i"] & mask, c["q"] & mask), (s[0] & mask, s[1] & mask))

    def test_dram_replay(self):
        from litedram.common import LiteDRAMNativePort
        n    = 16
        base = 0x80
        port = LiteDRAMNativePort("read", address_width=24, data_width=64)
        dut  = LiteDSPDMAReplay(data_width=16, port=port)
        dut.reader._base.storage.reset   = base
        dut.reader._length.storage.reset = n*4
        dut.reader._enable.storage.reset = 1
        samples = [(400*k + 4, -(400*k + 4)) for k in range(n)]
        mem = {(base >> 3) + k: iq_word(samples[2*k:2*k+2]) for k in range(n // 2)}
        cap = []
        run_simulation(dut, [
            dram_read_responder(port, mem),
            stream_capture(dut.source, cap, n, ("i", "q"), ready_rate=0.7),
        ])
        mask = 0xFFFF
        for s, c in zip(samples, cap):
            self.assertEqual((c["i"] & mask, c["q"] & mask), (s[0] & mask, s[1] & mask))

if __name__ == "__main__":
    unittest.main()
