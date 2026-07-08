// This file is part of LiteDSP.
// Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
// SPDX-License-Identifier: BSD-2-Clause
//
// Generic Verilator testbench for single-sink/single-source streaming blocks. The per-block
// port map (TB_DUT, TB_N_IN/TB_N_OUT, tb_set_in/tb_get_out) is generated into tb_ports.h by
// sim/run_blocks.py from the block's stream layouts.
// Usage: V<top> <in_file> <n_out> <out_file>   (in_file: TB_N_IN integer columns per line)

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <vector>
#include "tb_ports.h"
#include "verilated.h"

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    TB_DUT* dut = new TB_DUT;

    std::vector<std::vector<int32_t>> cols(TB_N_IN ? TB_N_IN : 1);
#if TB_N_IN
    FILE* fin = fopen(argv[1], "r");
    while (true) {
        int32_t v; bool ok = true;
        for (int k = 0; k < TB_N_IN; k++) {
            if (fscanf(fin, "%d", &v) != 1) { ok = false; break; }
            cols[k].push_back(v);
        }
        if (!ok) break;
    }
    fclose(fin);
#endif
    size_t n_in  = TB_N_IN ? cols[0].size() : 0;
    int    n_out = atoi(argv[2]);
    FILE*  fout  = fopen(argv[3], "w");

    auto posedge = [&]() { dut->sys_clk = 1; dut->eval(); dut->sys_clk = 0; dut->eval(); };

    dut->sys_clk = 0; dut->sys_rst = 1; dut->eval();
    for (int i = 0; i < 4; i++) posedge();
    dut->sys_rst = 0;

    size_t in_i = 0;
    int out_n = 0, guard = 0;
    while (out_n < n_out && guard++ < (int)(n_in + n_out) * 16 + 256) {
#if TB_N_IN
        dut->sink_valid = (in_i < n_in);
        if (in_i < n_in)
            for (int k = 0; k < TB_N_IN; k++) tb_set_in(dut, k, cols[k][in_i]);
#endif
        dut->source_ready = 1;
        dut->eval();                                   // settle combinational at clk=0
#if TB_N_IN
        bool consume = dut->sink_valid && dut->sink_ready;
#else
        bool consume = false;
#endif
        bool emit = dut->source_valid;
        if (emit && out_n < n_out) {
            for (int k = 0; k < TB_N_OUT; k++) fprintf(fout, "%d ", tb_get_out(dut, k));
            fprintf(fout, "\n");
            out_n++;
        }
        posedge();                                     // perform the transfer / state update
        if (consume) in_i++;
    }
    fclose(fout);
    delete dut;
    return out_n == n_out ? 0 : 1;
}
