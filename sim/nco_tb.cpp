// This file is part of LiteDSP.
// Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
// SPDX-License-Identifier: BSD-2-Clause
//
// Verilator testbench for the NCO: clock it, drive phase_inc, capture I/Q.
// Usage: Vnco <phase_inc> <n_samples> <out_file>

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include "Vnco.h"
#include "verilated.h"

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vnco* dut = new Vnco;

    uint32_t phase_inc = (uint32_t)strtoul(argv[1], nullptr, 10);
    int      n         = atoi(argv[2]);
    FILE*    f         = fopen(argv[3], "w");

    dut->phase_inc    = phase_inc;
    dut->source_ready = 1;

    auto tick = [&]() {
        dut->sys_clk = 0; dut->eval();
        dut->sys_clk = 1; dut->eval();   // rising edge: registers update
    };

    dut->sys_rst = 1;
    for (int i = 0; i < 4; i++) tick();
    dut->sys_rst = 0;

    int count = 0, guard = 0;
    while (count < n && guard++ < n * 8 + 64) {
        tick();
        if (dut->source_valid && dut->source_ready) {
            fprintf(f, "%d %d\n", (int16_t)dut->source_payload_i, (int16_t)dut->source_payload_q);
            count++;
        }
    }
    fclose(f);
    delete dut;
    return 0;
}
