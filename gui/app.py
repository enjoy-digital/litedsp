#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""DearPyGui flow-graph editor: wire LiteDSP blocks into a chain and generate gateware.

Left panel: the block palette (from the registry). Center: a node editor where each block node has
an input attribute per sink port, an output attribute per source port, and inline param fields.
Top toolbar: add top-level AXI-Stream input/output ports, Load/Save the netlist JSON, and Generate
(chain Verilog) / Generate IP (AXI-Stream + AXI-Lite + register map). All generation goes through
the headless backend (:mod:`litedsp.flow`), so the GUI adds no codegen logic.

Run: ``python -m gui.app``.
"""

import os
import traceback

from litedsp.flow import netlist as nlmod
from litedsp.flow import registry
from litedsp.flow.generate import generate
from litedsp.flow.ipcore   import generate_ip

from gui import graph, palette
from gui.params import coerce_params


class FlowEditor:
    def __init__(self):
        import dearpygui.dearpygui as dpg
        self.dpg = dpg
        self.reg = registry.registry()
        self.nodes   = {}      # node_id -> {"type", "params": {pname: widget_tag}}
        self.attrs   = {}      # dpg attribute id -> (node_id, port, direction)
        self.links   = {}      # dpg link id -> (src_ref, dst_ref)
        self._counter = {}

    # -- model helpers --------------------------------------------------------------------------
    def _new_id(self, key):
        self._counter[key] = self._counter.get(key, 0) + 1
        nid = f"{key}{self._counter[key]}".lower()
        nid = "".join(c if (c.isalnum() or c == "_") else "_" for c in nid)
        return nid

    def _ref(self, attr_id):
        nid, port, _ = self.attrs[attr_id]
        return nid if port is None else f"{nid}.{port}"

    # -- node creation --------------------------------------------------------------------------
    def add_block(self, key):
        dpg = self.dpg
        spec = self.reg[key]
        nid  = self._new_id(key)
        with dpg.node(label=f"{spec.display_name} [{nid}]", parent="editor", tag=f"node_{nid}"):
            for p in spec.sinks:
                a = dpg.add_node_attribute(attribute_type=dpg.mvNode_Attr_Input, label=p.name)
                dpg.add_text(f"> {p.name} ({p.layout})", parent=a)
                self.attrs[a] = (nid, p.name, "sink")
            param_tags = {}
            with dpg.node_attribute(attribute_type=dpg.mvNode_Attr_Static):
                for prm in spec.params:
                    if prm.name in ("data_width",):
                        continue
                    tag = f"param_{nid}_{prm.name}"
                    if prm.choices:
                        dpg.add_combo(prm.choices, default_value=str(prm.default),
                            label=prm.name, width=120, tag=tag)
                    elif prm.kind == "bool":
                        dpg.add_checkbox(label=prm.name, default_value=bool(prm.default), tag=tag)
                    else:
                        dpg.add_input_text(label=prm.name, default_value=str(prm.default),
                            width=120, tag=tag)
                    param_tags[prm.name] = tag
            for p in spec.sources:
                a = dpg.add_node_attribute(attribute_type=dpg.mvNode_Attr_Output, label=p.name)
                dpg.add_text(f"{p.name} ({p.layout}) >", parent=a)
                self.attrs[a] = (nid, p.name, "source")
        self.nodes[nid] = {"type": key, "params": param_tags}

    def add_io(self, kind):
        dpg = self.dpg
        nid = self._new_id("in" if kind == graph.INPUT_TYPE else "out")
        with dpg.node(label=f"{'INPUT' if kind == graph.INPUT_TYPE else 'OUTPUT'} [{nid}]",
                      parent="editor", tag=f"node_{nid}"):
            direction = "source" if kind == graph.INPUT_TYPE else "sink"
            attr_type = dpg.mvNode_Attr_Output if kind == graph.INPUT_TYPE else dpg.mvNode_Attr_Input
            a = dpg.add_node_attribute(attribute_type=attr_type)
            dpg.add_text("iq")
            self.attrs[a] = (nid, None, direction)
        self.nodes[nid] = {"type": kind, "params": {}}

    # -- link callbacks -------------------------------------------------------------------------
    def on_link(self, sender, app_data):
        a1, a2 = app_data
        d1, d2 = self.attrs[a1][2], self.attrs[a2][2]
        src, dst = (a1, a2) if d1 == "source" else (a2, a1)
        link = self.dpg.add_node_link(a1, a2, parent=sender)
        self.links[link] = (self._ref(src), self._ref(dst))

    def on_delink(self, sender, app_data):
        self.links.pop(app_data, None)
        self.dpg.delete_item(app_data)

    # -- model -> netlist -----------------------------------------------------------------------
    def to_netlist(self):
        dpg = self.dpg
        model_nodes = []
        for nid, n in self.nodes.items():
            if n["type"] in (graph.INPUT_TYPE, graph.OUTPUT_TYPE):
                model_nodes.append({"id": nid, "type": n["type"], "params": {"layout": "iq"}})
            else:
                spec = self.reg[n["type"]]
                raw  = {pn: dpg.get_value(tag) for pn, tag in n["params"].items()}
                model_nodes.append({"id": nid, "type": n["type"],
                                    "params": coerce_params(spec, raw)})
        meta = {"name": dpg.get_value("cfg_name") or "chain",
                "data_width": int(dpg.get_value("cfg_dw") or 16),
                "clock_ns": float(dpg.get_value("cfg_clk") or 10.0)}
        return graph.model_to_netlist(meta, model_nodes, list(self.links.values()))

    # -- actions --------------------------------------------------------------------------------
    def _log(self, msg):
        self.dpg.set_value("logbox", msg)

    def do_save(self, sender, app_data):
        try:
            nl = self.to_netlist()
            path = app_data["file_path_name"]
            nlmod.save(nl, path)
            self._log(f"Saved netlist: {path}")
        except Exception as e:
            self._log(f"Save failed:\n{e}")

    def do_load(self, sender, app_data):
        self._log("Load: re-open the JSON via the headless CLI for now "
                  "(in-canvas reload lands next); validated on Generate.")

    def do_generate(self, ip=False):
        try:
            nl = self.to_netlist()
            out = os.path.join("build", nl.name + ("_ip" if ip else ""))
            if ip:
                path, core = generate_ip(nl, out)
                self._log(f"Generated IP: {path}\nRegister map: {out}/csr.csv ({len(core.chain.get_csrs())} CSRs)")
            else:
                path, chain = generate(nl, out)
                extra = ("\nwarnings:\n  " + "\n  ".join(chain.flow_warnings)) if chain.flow_warnings else ""
                self._log(f"Generated Verilog: {path}{extra}")
        except Exception as e:
            self._log("Generate failed:\n" + "".join(traceback.format_exception_only(type(e), e)))

    # -- UI -------------------------------------------------------------------------------------
    def build(self):
        dpg = self.dpg
        with dpg.window(tag="main"):
            with dpg.group(horizontal=True):
                dpg.add_input_text(label="name", tag="cfg_name", default_value="chain", width=120)
                dpg.add_input_text(label="data_width", tag="cfg_dw", default_value="16", width=60)
                dpg.add_input_text(label="clock_ns", tag="cfg_clk", default_value="10.0", width=60)
                dpg.add_button(label="+ Input",  callback=lambda: self.add_io(graph.INPUT_TYPE))
                dpg.add_button(label="+ Output", callback=lambda: self.add_io(graph.OUTPUT_TYPE))
                dpg.add_button(label="Save", callback=lambda: dpg.show_item("save_dlg"))
                dpg.add_button(label="Generate",    callback=lambda: self.do_generate(ip=False))
                dpg.add_button(label="Generate IP", callback=lambda: self.do_generate(ip=True))
            with dpg.group(horizontal=True):
                with dpg.child_window(width=230, tag="palette"):
                    for cat, specs in palette.categories().items():
                        with dpg.collapsing_header(label=cat):
                            for spec in specs:
                                dpg.add_button(label=spec.display_name, width=-1,
                                    user_data=spec.key,
                                    callback=lambda s, a, u: self.add_block(u))
                    dpg.add_separator()
                    dpg.add_text("", tag="logbox", wrap=210)
                dpg.add_node_editor(tag="editor", callback=self.on_link,
                    delink_callback=self.on_delink, minimap=True)
        with dpg.file_dialog(directory_selector=False, show=False, tag="save_dlg",
                             default_filename="chain.json", callback=self.do_save, width=600, height=400):
            dpg.add_file_extension(".json")


def main():
    import dearpygui.dearpygui as dpg
    dpg.create_context()
    editor = FlowEditor()
    editor.build()
    dpg.create_viewport(title="LiteDSP Flow Editor", width=1280, height=800)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main", True)
    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    main()
