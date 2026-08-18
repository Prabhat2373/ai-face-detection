"""Repair legacy custom exports created with an invalid PReLU ONNX graph."""

from __future__ import annotations

import sys
from pathlib import Path

import onnx
from onnx import helper


def repair(path: Path) -> None:
    model = onnx.load(str(path))
    consumers = {}
    for node in model.graph.node:
        for input_name in node.input:
            consumers.setdefault(input_name, []).append(node)

    remove_names: set[str] = set()
    replacements = []
    for node in model.graph.node:
        if node.op_type != "PRelu" or len(node.input) != 2:
            continue
        slope_input = node.input[1]
        slope_nodes = [n for n in consumers.get(slope_input, []) if n.op_type == "Unsqueeze"]
        replacements.append(helper.make_node(
            "LeakyRelu",
            inputs=[node.input[0]],
            outputs=list(node.output),
            name=node.name or f"{node.output[0]}_LeakyRelu",
            alpha=0.25,
        ))
        remove_names.add(node.name)
        remove_names.update(n.name for n in slope_nodes)

    if not replacements:
        print(f"No legacy PReLU nodes found in {path}; checking for orphaned export nodes")

    replacement_by_output = {output: node for node in replacements for output in node.output}
    nodes = []
    for node in model.graph.node:
        if node.name in remove_names:
            replacement = replacement_by_output.get(node.output[0])
            if replacement is not None:
                nodes.append(replacement)
            continue
        nodes.append(node)
    # Quantized exports can leave the old slope Unsqueeze nodes orphaned.
    used_inputs = {input_name for node in nodes for input_name in node.input}
    nodes = [
        node for node in nodes
        if not (node.op_type == "Unsqueeze" and node.output and node.output[0] not in used_inputs)
    ]
    del model.graph.node[:]
    model.graph.node.extend(nodes)
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    print(f"Repaired {path}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    paths = [Path(arg) for arg in sys.argv[1:]] or [
        root / "weights/custom_student/student_std_512d_fp32.onnx",
        root / "weights/custom_student/student_std_512d_int8.onnx",
    ]
    for model_path in paths:
        repair(model_path)
