// This file is part of LiteDSP.
// Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
// SPDX-License-Identifier: BSD-2-Clause
//
// Verilator testbench for FIRFilterComplex: stream samples from a file, capture outputs.
// Usage: Vfir <in_file> <n_out> <out_file>   (in_file: "i q" per line)

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <vector>
#include "Vfir.h"
#include "verilated.h"

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vfir* dut = new Vfir;

    std::vector<int> xi, xq;
    FILE* fin = fopen(argv[1], "r");
    int a, b;
    while (fscanf(fin, "%d %d", &a, &b) == 2) { xi.push_back(a); xq.push_back(b); }
    fclose(fin);
    int n_out = atoi(argv[2]);
    FILE* fout = fopen(argv[3], "w");

    dut->bypass = 0;
    auto posedge = [&]() { dut->sys_clk = 1; dut->eval(); dut->sys_clk = 0; dut->eval(); };

    dut->sys_clk = 0; dut->sys_rst = 1; dut->eval();
    for (int i = 0; i < 4; i++) posedge();
    dut->sys_rst = 0;

    size_t in_i = 0;
    int out_n = 0, guard = 0;
    while (out_n < n_out && guard++ < (int)(xi.size() + n_out) * 8 + 256) {
        dut->sink_valid = (in_i < xi.size());
        if (in_i < xi.size()) { dut->sink_payload_i = xi[in_i]; dut->sink_payload_q = xq[in_i]; }
        dut->source_ready = 1;
        dut->eval();                                   // settle combinational at clk=0
        bool consume = dut->sink_valid && dut->sink_ready;
        bool emit    = dut->source_valid && dut->source_ready;
        if (emit && out_n < n_out) {
            fprintf(fout, "%d %d\n", (int16_t)dut->source_payload_i, (int16_t)dut->source_payload_q);
            out_n++;
        }
        posedge();                                     // perform the transfer / state update
        if (consume) in_i++;
    }
    fclose(fout);
    delete dut;
    return 0;
}
