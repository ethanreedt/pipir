"""Build the diagram-ready graph JSON for one pipeline."""

import hashlib

from ..convert import build_pipeline
from ..emit import emit
from ..lint import lint_pipeline

NODE_W = 190
NODE_H = 60
COL_GAP = 270
ROW_GAP = 100


def _node_blocks(ir_text):
    """Map node ref -> (start_line, block text) from the canonical IR."""
    blocks = {}
    lines = ir_text.splitlines()
    ref, start = None, 0
    for i, line in enumerate(lines):
        if line.startswith("node "):
            if ref:
                blocks[ref] = (start, "\n".join(lines[start - 1:i]).rstrip())
            ref, start = line.split()[1], i + 1
        elif ref and line and not line.startswith(" "):
            blocks[ref] = (start, "\n".join(lines[start - 1:i]).rstrip())
            ref = None
    if ref:
        blocks[ref] = (start, "\n".join(lines[start - 1:]).rstrip())
    return blocks


def content_hash(ref, block):
    """Hash of a node's content, independent of its mangled ordinal."""
    body = block.split("\n", 1)
    head = body[0].replace("node %s " % ref, "node ", 1)
    rest = body[1] if len(body) > 1 else ""
    return hashlib.sha1((head + "\n" + rest).encode("utf-8")).hexdigest()[:16]


def build_graph(doc, name_fallback=None):
    pipe = build_pipeline(doc, name_fallback)
    ir_text = emit(pipe)
    findings = lint_pipeline(pipe, ir_text)
    blocks = _node_blocks(ir_text)

    # Layered layout: column = topological depth, row = order within column.
    by_id = {n.instance_id: n for n in pipe.nodes}
    depth = {n.instance_id: 0 for n in pipe.nodes}
    for e in pipe.edges:  # emission order is topological
        depth[e.dst_id] = max(depth[e.dst_id], depth[e.src_id] + 1)
    columns = {}
    for n in pipe.nodes:
        columns.setdefault(depth[n.instance_id], []).append(n)
    max_rows = max((len(c) for c in columns.values()), default=1)

    nodes = []
    pos = {}
    for col, members in sorted(columns.items()):
        for row, n in enumerate(members):
            x = col * COL_GAP
            y = row * ROW_GAP + (max_rows - len(members)) * ROW_GAP / 2
            pos[n.instance_id] = (x, y)
            line, block = blocks.get(n.ref, (0, ""))
            nodes.append({
                "ref": n.ref, "kind": n.kind, "native": n.native,
                "label": n.label, "x": x, "y": y, "line": line,
                "block": block, "hash": content_hash(n.ref, block),
                "in": [p.slot for p in n.inputs],
                "out": [p.slot for p in n.outputs],
                "err": [p.slot for p in n.errors],
                "instance_id": n.instance_id,
            })

    edges = []
    for e in pipe.edges:
        src, dst = by_id[e.src_id], by_id[e.dst_id]
        sslot = src.slot_by_key.get(e.src_view, e.src_view)
        dslot = dst.slot_by_key.get(e.dst_view, e.dst_view)
        edges.append({"src": src.ref, "srcPort": sslot,
                      "dst": dst.ref, "dstPort": dslot,
                      "error": sslot.startswith("err")})

    return {
        "name": pipe.name, "ir": ir_text,
        "params": [p.name for p in pipe.params],
        "nodes": nodes, "edges": edges,
        "findings": [f.__dict__ for f in findings],
        "size": {"w": NODE_W, "h": NODE_H},
    }
