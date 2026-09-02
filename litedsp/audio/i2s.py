#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""I2S / left-justified / right-justified / TDM serial audio receiver and transmitter, master or
slave, running entirely in the ``sys`` clock domain (a master divides ``sys`` into BCLK; a slave
synchronizes BCLK/LRCK/SDATA and detects their edges)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, tdm_layout, tdm_channel, scaled

FORMATS = ("i2s", "left_justified", "right_justified", "tdm")
MODES   = ("master", "slave")

def _format_params(fmt, sample_width, slot_width):
    """``(msb_pos, polarity)``: the bit position of the MSB inside a slot (counted from the LRCK
    transition / frame-sync bit) and the LRCK level that carries channel 0 (``None`` for the
    TDM frame-sync pulse)."""
    if fmt == "i2s":
        return 1, 0
    if fmt == "left_justified":
        return 0, 1
    if fmt == "right_justified":
        return slot_width - sample_width, 1
    return 1, None                                                     # tdm.

def _check_params(data_width, sample_width, slot_width, n_channels, fmt, mode, bclk_div):
    check(fmt in FORMATS, f"expected fmt in {FORMATS}")
    check(mode in MODES, f"expected mode in {MODES}")
    check(slot_width in (16, 24, 32), "expected slot_width in (16, 24, 32)")
    check(8 <= sample_width <= min(slot_width, data_width), "expected 8 <= sample_width <= min(slot_width, data_width)")
    check(bclk_div >= 4 and bclk_div % 2 == 0, "expected an even bclk_div >= 4")
    if fmt == "tdm":
        check(n_channels in (2, 4, 8), "expected n_channels in (2, 4, 8) for tdm")
    else:
        check(n_channels == 2, "expected n_channels == 2 (stereo frame) for this fmt")

def _bit_clock(module, mode, bclk_div, bclk, lrck, sdata):
    """Bit-clock strobes in the ``sys`` domain.

    Master: ``bclk`` toggles every ``bclk_div/2`` cycles; ``fall`` strobes the cycle *before*
    the falling toggle (registers updated on it change together with BCLK) and ``rise`` the
    cycle after the rising toggle (sampling). Slave: 2-FF synchronizers on the three lines and
    edge detection (``sys`` must run at >= 4 x BCLK). Returns ``(rise, fall, lrck_s,
    sdata_s)``: the line levels valid at the strobes.
    """
    rise, fall = Signal(), Signal()
    if mode == "master":
        half   = bclk_div//2
        cnt    = Signal(max=half)
        bclk_d = Signal()
        sd     = Signal()
        module.sync += [
            If(cnt == half - 1, cnt.eq(0), bclk.eq(~bclk)).Else(cnt.eq(cnt + 1)),
            bclk_d.eq(bclk),
            sd.eq(sdata),
        ]
        module.comb += [rise.eq(bclk & ~bclk_d), fall.eq((cnt == half - 1) & bclk)]
        return rise, fall, lrck, sd
    b = Signal(3)
    l = Signal(2)
    d = Signal(2)
    module.sync += [b.eq(Cat(bclk, b[:2])), l.eq(Cat(lrck, l[0])), d.eq(Cat(sdata, d[0]))]
    module.comb += [rise.eq(b[1] & ~b[2]), fall.eq(~b[1] & b[2])]
    return rise, fall, l[1], d[1]

def _frame_position(module, ev, mode, fmt, polarity, slot_width, n_channels, lrck_s, lrck_out):
    """Slot bit position and slot index of the bit handled at strobe ``ev``.

    Master: free-running counters advanced at ``ev`` (``lrck_out`` is driven for the next
    bit). Slave: recovered from the LRCK transitions (stereo formats) or the frame-sync pulse
    (TDM) seen at ``ev``. Returns ``(pos, slot, frame_start)`` valid during ``ev``.
    """
    pos, slot, frame_start = Signal(max=slot_width), Signal(max=max(2, n_channels)), Signal()
    if mode == "master":
        pos_r  = Signal(max=slot_width, reset=slot_width - 1)
        slot_r = Signal(max=max(2, n_channels), reset=n_channels - 1)
        wrap   = pos_r == slot_width - 1
        module.comb += [
            pos.eq(Mux(wrap, 0, pos_r + 1)),
            slot.eq(Mux(wrap, Mux(slot_r == n_channels - 1, 0, slot_r + 1), slot_r)),
            frame_start.eq((pos == 0) & (slot == 0)),
        ]
        level = ((pos == 0) & (slot == 0)) if polarity is None else ((slot == 0) == polarity)
        module.sync += If(ev, pos_r.eq(pos), slot_r.eq(slot), lrck_out.eq(level))
        return pos, slot, frame_start
    pos_r, slot_r = Signal(max=slot_width), Signal(max=max(2, n_channels))
    lrck_prev     = Signal()
    change        = Signal()
    module.comb += change.eq(lrck_s != lrck_prev)
    if polarity is None:                                               # TDM: sync pulse.
        wrap = pos_r == slot_width - 1
        module.comb += [
            frame_start.eq(change & lrck_s),
            pos.eq(Mux(frame_start | wrap, 0, pos_r + 1)),
            slot.eq(Mux(frame_start, 0, Mux(wrap, Mux(slot_r == n_channels - 1, 0, slot_r + 1), slot_r))),
        ]
    else:                                                              # Stereo: LRCK level.
        module.comb += [
            frame_start.eq(change & (lrck_s == polarity)),
            pos.eq(Mux(change, 0, Mux(pos_r == slot_width - 1, pos_r, pos_r + 1))),
            slot.eq(Mux(change, Mux(lrck_s == polarity, 0, 1), slot_r)),
        ]
    module.sync += If(ev, pos_r.eq(pos), slot_r.eq(slot), lrck_prev.eq(lrck_s))
    return pos, slot, frame_start

# I2S Receiver -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPI2SReceiver(LiteXModule):
    """Serial audio receiver (I2S, left/right-justified, TDM) to a channel-tagged TDM stream.

    Data is sampled on the BCLK rising edge, MSB first, ``sample_width`` bits per
    ``slot_width`` slot: I2S (MSB one BCLK after the LRCK transition, left = LRCK low),
    left-justified (MSB at the transition, left = LRCK high), right-justified (LSB at the slot
    end) and TDM (``lrck`` is a one-BCLK frame-sync pulse, ``n_channels`` consecutive slots).
    Words are MSB-aligned into ``data_width`` and tagged with their slot; a word completing
    while the previous one is still unread is dropped (sticky ``overrun``). ``mode="master"``
    drives ``bclk``/``lrck`` at ``sys_clk / bclk_div``; ``mode="slave"`` follows them (``sys``
    >= 4 x BCLK). Source-only, ``latency = None``.
    """
    def __init__(self, data_width=24, sample_width=24, slot_width=32, n_channels=2, fmt="i2s",
        mode="slave", bclk_div=8, with_csr=True):
        _check_params(data_width, sample_width, slot_width, n_channels, fmt, mode, bclk_div)
        self.data_width   = data_width
        self.sample_width = sample_width
        self.slot_width   = slot_width
        self.n_channels   = n_channels
        self.fmt          = fmt
        self.mode         = mode
        self.bclk_div     = bclk_div
        self.latency      = None
        self.source  = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.bclk    = Signal()                                            # Pins.
        self.lrck    = Signal()
        self.sdata   = Signal()
        self.enable  = Signal(reset=1)
        self.clear   = Signal()
        self.overrun = Signal()

        # # #

        msb_pos, polarity = _format_params(fmt, sample_width, slot_width)
        rise, fall, lrck_s, sdata_s = _bit_clock(self, mode, bclk_div, self.bclk, self.lrck, self.sdata)
        ev = Signal()
        self.comb += ev.eq(fall if mode == "master" else rise)
        # Master: positions advance at the falling edge (with LRCK); the bit on the line is
        # sampled at the following rising edge with the registered position.
        pos, slot, frame_start = _frame_position(self, ev, mode, fmt, polarity, slot_width,
            n_channels, lrck_s, self.lrck)
        # Words are captured from the first frame start on (a receiver enabled mid-stream waits
        # for channel 0 rather than emitting a partial word).
        synced   = Signal()
        synced_n = Signal()
        self.comb += synced_n.eq(synced | frame_start)
        self.sync += If(ev & frame_start & self.enable, synced.eq(1)).Elif(~self.enable, synced.eq(0))
        if mode == "master":
            pos_s, slot_s, sync_s = Signal(max=slot_width), Signal(max=max(2, n_channels)), Signal()
            self.sync += If(fall, pos_s.eq(pos), slot_s.eq(slot), sync_s.eq(synced_n))
            sample = rise
        else:
            pos_s, slot_s, sync_s, sample = pos, slot, synced_n, rise

        # Shift-in: start at the MSB position, capture sample_width bits (a slot boundary may
        # fall inside the word: the I2S one-bit delay).
        # ----------------------------------------------------------------------------------
        shift    = Signal(sample_width)
        rem      = Signal(max=sample_width + 1)
        slot_lat = Signal(max=max(2, n_channels))
        start    = Signal()
        done     = Signal()
        word     = Signal((sample_width, True))
        self.comb += [
            start.eq(sample & self.enable & sync_s & (pos_s == msb_pos)),
            done.eq(sample & ~start & (rem == 1)),
            word.eq(Cat(sdata_s, shift[:-1])),
        ]
        self.sync += [
            If(start,
                shift.eq(sdata_s), rem.eq(sample_width - 1), slot_lat.eq(slot_s),
            ).Elif(sample & (rem != 0),
                shift.eq(word), rem.eq(rem - 1),
            ),
            If(self.source.ready, self.source.valid.eq(0)),
            If(done,
                If(self.source.valid & ~self.source.ready,
                    self.overrun.eq(1),
                ).Else(
                    self.source.valid.eq(1),
                    self.source.data.eq(word << (data_width - sample_width)),
                    *([self.source.channel.eq(slot_lat)] if n_channels > 1 else []),
                ),
            ),
            If(self.clear, self.overrun.eq(0)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("enable", size=1, offset=0, reset=1, description="Capture words."),
            CSRField("clear",  size=1, offset=1, pulse=True, description="Clear overrun."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("overrun", size=1, offset=0, description="Sticky: a word was dropped."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("fmt",          size=2, offset=0,  description="0 i2s, 1 left-justified, 2 right-justified, 3 tdm."),
            CSRField("master",       size=1, offset=2,  description="Master (drives bclk/lrck)."),
            CSRField("n_channels",   size=4, offset=3,  description="Slots per frame."),
            CSRField("sample_width", size=6, offset=7,  description="Bits per sample."),
            CSRField("slot_width",   size=6, offset=13, description="Bits per slot."),
            CSRField("bclk_div",     size=8, offset=19, description="sys_clk / bclk (master)."),
        ])
        self.comb += [
            self.enable.eq(self._control.fields.enable),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.overrun.eq(self.overrun),
            self._config.fields.fmt.eq(FORMATS.index(self.fmt)),
            self._config.fields.master.eq(int(self.mode == "master")),
            self._config.fields.n_channels.eq(self.n_channels),
            self._config.fields.sample_width.eq(self.sample_width),
            self._config.fields.slot_width.eq(self.slot_width),
            self._config.fields.bclk_div.eq(self.bclk_div),
        ]

# I2S Transmitter ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPI2STransmitter(LiteXModule):
    """Channel-tagged TDM stream to serial audio (I2S, left/right-justified, TDM); the mirror of
    :class:`LiteDSPI2SReceiver`.

    Beats fill a frame buffer by tag (``sink.ready`` drops once every channel of the next frame
    is loaded); the buffer is committed at each frame start and shifted out MSB first, the data
    changing on the BCLK falling edge (a slave transmitter needs ``sys`` >= 8 x BCLK for its
    output to settle before the master's rising edge). Samples are rounded/saturated from
    ``data_width`` to ``sample_width``. A frame start without a complete buffer repeats the
    previous frame and sets the sticky ``underrun`` flag (once streaming has started).
    Sink-only, ``latency = None``.
    """
    def __init__(self, data_width=24, sample_width=24, slot_width=32, n_channels=2, fmt="i2s",
        mode="master", bclk_div=8, with_csr=True):
        _check_params(data_width, sample_width, slot_width, n_channels, fmt, mode, bclk_div)
        self.data_width   = data_width
        self.sample_width = sample_width
        self.slot_width   = slot_width
        self.n_channels   = n_channels
        self.fmt          = fmt
        self.mode         = mode
        self.bclk_div     = bclk_div
        self.latency      = None
        self.sink     = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.bclk     = Signal()                                           # Pins.
        self.lrck     = Signal()
        self.sdata    = Signal()
        self.enable   = Signal(reset=1)
        self.clear    = Signal()
        self.underrun = Signal()

        # # #

        msb_pos, polarity = _format_params(fmt, sample_width, slot_width)
        rise, fall, lrck_s, _ = _bit_clock(self, mode, bclk_div, self.bclk, self.lrck, Signal())
        pos, slot, frame_start = _frame_position(self, fall, mode, fmt, polarity, slot_width,
            n_channels, lrck_s, self.lrck)

        # Frame buffer filled by tag.
        # ---------------------------
        SW = sample_width
        next_words = Array(Signal((SW, True), name=f"next{c}") for c in range(n_channels))
        cur_words  = Array(Signal((SW, True), name=f"cur{c}") for c in range(n_channels))
        filled     = Signal(n_channels)
        full       = Signal()
        started    = Signal()
        ch         = tdm_channel(self.sink)
        xfer       = Signal()
        self.comb += [
            full.eq(filled == (1 << n_channels) - 1),
            self.sink.ready.eq(~full),
            xfer.eq(self.sink.valid & self.sink.ready),
        ]
        sample = self.sink.data if SW == data_width else scaled(self.sink.data, data_width - SW, SW)[0]
        for c in range(n_channels):
            self.sync += If(xfer & (ch == c), next_words[c].eq(sample), filled[c].eq(1))
        self.sync += If(fall & frame_start,
            If(full,
                *[cur_words[c].eq(next_words[c]) for c in range(n_channels)],
                filled.eq(0), started.eq(1),
            ).Elif(started,
                self.underrun.eq(1),
            ),
        )
        self.sync += If(self.clear, self.underrun.eq(0))

        # Shift-out: bit k = pos - msb_pos of the current slot; positions before the MSB carry
        # the previous slot's tail (the I2S one-bit delay).
        # ----------------------------------------------------------------------------------
        word      = Signal((SW, True))
        last_word = Signal((SW, True))
        k         = Signal((8, True))
        k_prev    = Signal((8, True))
        bit       = Signal()
        self.comb += [
            word.eq(Mux(frame_start & full, next_words[slot], cur_words[slot])),
            k.eq(pos - msb_pos),
            k_prev.eq(pos + (slot_width - msb_pos)),
            If((k >= 0) & (k < SW),
                bit.eq(word >> (SW - 1 - k)),
            ).Elif((k < 0) & (k_prev < SW),
                bit.eq(last_word >> (SW - 1 - k_prev)),
            ).Else(
                bit.eq(0),
            ),
        ]
        self.sync += If(fall,
            self.sdata.eq(bit & self.enable),
            If(pos == slot_width - 1, last_word.eq(word)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("enable", size=1, offset=0, reset=1, description="Drive sdata (0: silence)."),
            CSRField("clear",  size=1, offset=1, pulse=True, description="Clear underrun."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("underrun", size=1, offset=0, description="Sticky: a frame started without a full buffer."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("fmt",          size=2, offset=0,  description="0 i2s, 1 left-justified, 2 right-justified, 3 tdm."),
            CSRField("master",       size=1, offset=2,  description="Master (drives bclk/lrck)."),
            CSRField("n_channels",   size=4, offset=3,  description="Slots per frame."),
            CSRField("sample_width", size=6, offset=7,  description="Bits per sample."),
            CSRField("slot_width",   size=6, offset=13, description="Bits per slot."),
            CSRField("bclk_div",     size=8, offset=19, description="sys_clk / bclk (master)."),
        ])
        self.comb += [
            self.enable.eq(self._control.fields.enable),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.underrun.eq(self.underrun),
            self._config.fields.fmt.eq(FORMATS.index(self.fmt)),
            self._config.fields.master.eq(int(self.mode == "master")),
            self._config.fields.n_channels.eq(self.n_channels),
            self._config.fields.sample_width.eq(self.sample_width),
            self._config.fields.slot_width.eq(self.slot_width),
            self._config.fields.bclk_div.eq(self.bclk_div),
        ]
