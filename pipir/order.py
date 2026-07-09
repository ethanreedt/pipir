"""Deterministic node ordering and mangled-id assignment (SPEC.md §5).

Emission order is dataflow order: topological depth first, then content-based
tie-breaks. Ordering depends only on graph content, never on input iteration
order, linkNNN keys, or UUIDs — the stable instance_id is used only as a final
hidden tie-break between truly interchangeable nodes.
"""

import json

from .unwrap import Expr


def _jsonable(value):
    if isinstance(value, Expr):
        return {"__expr__": value.text}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _content_key(node):
    return json.dumps(_jsonable(node.settings), sort_keys=True, ensure_ascii=False)


def _depths(nodes, edges):
    """Longest-path-from-source depth per node, over data+error edges."""
    ids = {n.instance_id for n in nodes}
    out = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for e in edges:
        if e.src_id in ids and e.dst_id in ids:
            out[e.src_id].append(e.dst_id)
            indeg[e.dst_id] += 1
    depth = {i: 0 for i in ids}
    queue = [i for i in ids if indeg[i] == 0]
    seen = 0
    while queue:
        nid = queue.pop()
        seen += 1
        for dst in out[nid]:
            depth[dst] = max(depth[dst], depth[nid] + 1)
            indeg[dst] -= 1
            if indeg[dst] == 0:
                queue.append(dst)
    if seen != len(ids):
        # Cycle (shouldn't happen in SnapLogic, but don't loop forever):
        # unresolved nodes keep whatever depth they accumulated.
        pass
    return depth


def order_and_mangle(pipe):
    """Sort pipe.nodes into emission order and assign mangled refs; sort edges."""
    depth = _depths(pipe.nodes, pipe.edges)
    pipe.nodes.sort(key=lambda n: (
        depth.get(n.instance_id, 0),
        n.kind,
        n.native,
        n.label,
        _content_key(n),
        n.instance_id,          # hidden final tie-break; never emitted
    ))
    counters = {}
    by_id = {}
    for node in pipe.nodes:
        counters[node.mnemonic] = counters.get(node.mnemonic, 0) + 1
        node.ref = "%s.%d" % (node.mnemonic, counters[node.mnemonic])
        by_id[node.instance_id] = node

    index = {n.instance_id: i for i, n in enumerate(pipe.nodes)}

    def edge_key(e):
        src, dst = by_id.get(e.src_id), by_id.get(e.dst_id)
        return (
            index.get(e.src_id, len(index)),
            (src.slot_by_key.get(e.src_view, e.src_view) or "") if src else "",
            index.get(e.dst_id, len(index)),
            (dst.slot_by_key.get(e.dst_view, e.dst_view) or "") if dst else "",
        )

    pipe.edges = [e for e in pipe.edges
                  if e.src_id in by_id and e.dst_id in by_id]
    pipe.edges.sort(key=edge_key)
    return by_id
