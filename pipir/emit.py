"""Render the model as canonical ETL-IR text (SPEC.md §2, §3, §9).

Canonical bytes: 2-space indents, \\n endings, one trailing newline, sections
in fixed order, set lines sorted by dotted path.
"""

import json
import re

from . import IR_VERSION
from .unwrap import Expr

_BAREWORD = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _jstr(s):
    return json.dumps(s, ensure_ascii=False)


def render_value(value):
    """One-line IR rendering of an unwrapped scalar/Expr/collection value."""
    if isinstance(value, Expr):
        return "expr null" if value.text is None else "expr " + _jstr(value.text)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return _jstr(value)
    if isinstance(value, list) and not value:
        return "[]"
    if isinstance(value, dict) and not value:
        return "{}"
    return None  # non-empty collection: caller flattens instead


def _path_seg(seg):
    return seg if _BAREWORD.match(seg) else "[%s]" % _jstr(seg)


def _join_path(base, seg):
    quoted = _path_seg(seg)
    if quoted.startswith("["):
        return base + quoted
    return "%s.%s" % (base, seg) if base else seg


def flatten_setting(path, value, out):
    """Flatten one setting to (path, rendered) leaf lines (SPEC §2.2)."""
    rendered = render_value(value)
    if rendered is not None:
        out.append((path, rendered))
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            flatten_setting("%s[%d]" % (path, i), item, out)
    elif isinstance(value, dict):
        for key in sorted(value):
            flatten_setting(_join_path(path, key), value[key], out)
    else:  # unexpected leaf type; preserve via JSON
        out.append((path, _jstr(json.dumps(value, sort_keys=True))))


def _set_lines(settings):
    leaves = []
    for key in sorted(settings):
        flatten_setting(_path_seg(key), settings[key], leaves)
    lines = []
    for path, rendered in leaves:
        # Multi-line strings/expressions -> block form (SPEC §2.1).
        if rendered.startswith('"') and "\\n" in rendered:
            head, raw = "set %s |" % path, json.loads(rendered)
        elif rendered.startswith('expr "') and "\\n" in rendered:
            head, raw = "set %s expr |" % path, json.loads(rendered[5:])
        else:
            lines.append("set %s %s" % (path, rendered))
            continue
        lines.append(head)
        lines.extend("  " + line for line in raw.split("\n"))
    return lines


def _note_lines(text):
    return ["; note: " + line if line else "; note:"
            for line in text.strip().splitlines()]


def _port_line(kw, port):
    parts = [kw, port.slot]
    if port.binary:
        parts.append("binary")
    if port.behavior:
        parts.append(port.behavior)
    if port.label is not None:
        parts.append("label " + _jstr(port.label))
    return " ".join(parts)


def _account_line(account):
    if account.expr is not None:
        return "account " + render_value(account.expr)
    parts = ["account", render_value(account.name)]
    if account.type:
        parts += ["type", account.type]
    return " ".join(parts)


def _node_block(node):
    lines = ["node %s %s native=%s" % (node.ref, node.kind, node.native)]
    body = ["label " + _jstr(node.label)]
    if node.notes:
        body.extend(_note_lines(node.notes))
    for port in node.inputs:
        body.append(_port_line("in", port))
    for port in node.outputs:
        body.append(_port_line("out", port))
    for port in node.errors:
        body.append(_port_line("err", port))
    if node.account:
        body.append(_account_line(node.account))
    body.extend(node.statements)
    body.extend(_set_lines(node.settings))
    lines.extend("  " + line for line in body)
    return lines


def _param_line(param):
    parts = ["param", param.name]
    if not param.capture:
        parts.append("nocapture")
    if param.default is not None:
        parts.append(render_value(param.default))
    return " ".join(parts)


def emit(pipe):
    out = ["etl-ir " + IR_VERSION, "dialect snaplogic", ""]
    line = "pipeline " + _jstr(pipe.name)
    if pipe.name_from_filename:
        line += " ; name from filename (export carries no label)"
    out.append(line)
    out.append("")

    if pipe.params:
        out.extend(_param_line(p) for p in pipe.params)
        out.append("")

    header = []
    for imp in pipe.imports:
        header.append("import " + render_value(imp))
    if pipe.error_pipeline is not None:
        header.append("on-error pipeline " + render_value(pipe.error_pipeline))
        for key, val in pipe.error_args:
            header.append("  arg %s %s" % (key, render_value(val)))
    if pipe.error_behavior and pipe.error_behavior != "none":
        header.append("on-error behavior " + pipe.error_behavior)
    if header:
        out.extend(header)
        out.append("")

    for node in pipe.nodes:
        out.extend(_node_block(node))
        out.append("")

    by_id = {n.instance_id: n for n in pipe.nodes}
    edge_lines = []
    for e in pipe.edges:
        src, dst = by_id[e.src_id], by_id[e.dst_id]
        edge_lines.append("edge %s:%s -> %s:%s" % (
            src.ref, src.slot_by_key.get(e.src_view, e.src_view),
            dst.ref, dst.slot_by_key.get(e.dst_view, e.dst_view)))
    if edge_lines:
        out.extend(edge_lines)
        out.append("")

    io_lines = []
    for direction, snap_id, view_key, label in sorted(
            pipe.open_views,
            key=lambda v: (v[0], by_id[v[1]].ref if v[1] in by_id else "", v[2])):
        node = by_id.get(snap_id)
        if node is None:
            continue
        slot = node.slot_by_key.get(view_key, view_key)
        line = "pipeline-%s %s:%s" % (direction, node.ref, slot)
        if label:
            line += " label " + _jstr(label)
        io_lines.append(line)
    if io_lines:
        out.extend(io_lines)
        out.append("")

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"
