#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Standalone cores and their pin-level neighbours: FOC core + PWM, I2S around the audio core.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    host = d.add(Box(20, 15, 720, 36, label="Host register bus", fill=COLOR_HARDWARE))
    adc  = d.add(Box(20,  95, 150, 50, label="Currents, angle"))
    foc  = d.add(Box(230, 95, 150, 50, label="foc_core", fill=COLOR_ACCENT))
    pwm  = d.add(Box(440, 95, 150, 50, label="LiteDSPPWM", fill=COLOR_ACCENT_LIGHT))
    gat  = d.add(Box(650, 95, 90, 50, label="Gates", fill=COLOR_HARDWARE))
    rx   = d.add(Box(20,  185, 150, 50, label="I2S receiver", fill=COLOR_ACCENT_LIGHT))
    aud  = d.add(Box(230, 185, 150, 50, label="audio_core", fill=COLOR_ACCENT))
    tx   = d.add(Box(440, 185, 150, 50, label="I2S transmitter", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((adc, "r"), (foc, "l"), kind="data"))
    d.add(Arrow((foc, "r"), (pwm, "l"), kind="data", label="duties"))
    d.add(Arrow((pwm, "r"), (gat, "l")))
    d.add(Arrow((rx, "r"), (aud, "l"), kind="data", label="TDM"))
    d.add(Arrow((aud, "r"), (tx, "l"), kind="data", label="TDM"))
    d.add(Arrow((foc.cx, host.y + host.h), (foc, "t"), heads="both"))
    d.add(Arrow((pwm.cx, host.y + host.h), (pwm, "t"), heads="both"))
    d.add(Arrow((200, host.y + host.h), (260, aud.y), via=[(200, 165), (260, 165)], heads="both"))
    return d
