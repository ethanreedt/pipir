"""pipir lint — static analysis over the pipeline model.

    python -m pipir.lint input.slp [--json] [--level info|warn|error]

Checks (severity):
  field-missing     (error) field read downstream of a passthrough-off Mapper
                    that provably does not provide it
  undeclared-param  (error) expression references _name with no declared param
  error-unwired     (warn)  error view set to route-to-error-view but unwired
  null-param        (warn)  param with null default dereferenced without guard
  router-gap        (warn)  first-match off and routes not obviously exhaustive
  dup-target        (warn)  duplicate targetPath rows in one mapping table
  unused-param      (info)  declared param never referenced
  output-unwired    (info)  declared output port with no edge

Findings anchor to the node's `node <ref> …` line in the canonical IR.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass

from .emit import emit
from .extract import extract
from .order import order_and_mangle
from .parse_slp import parse_slp
from .unwrap import Expr

SEVERITIES = ("info", "warn", "error")

_STRINGS = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_PARAM = re.compile(r"(?<![\w$.])_([A-Za-z]\w*)")
_FIELD = re.compile(r"\$([A-Za-z_]\w*)")
_FIELD_Q = re.compile(r"\$\[\s*(['\"])(.*?)\1\s*\]")


@dataclass
class Finding:
    check: str
    severity: str        # info | warn | error
    ref: str             # node ref, or "" for pipeline-level
    message: str
    line: int = 0        # 1-based line in the canonical IR, 0 if n/a


def _strip_strings(text):
    return _STRINGS.sub('""', text)


def param_refs(text):
    return set(_PARAM.findall(_strip_strings(text)))


def field_roots(text):
    body = _strip_strings(text)
    roots = set(_FIELD.findall(body))
    roots.update(m.group(2) for m in _FIELD_Q.finditer(text))
    return roots


def _walk_exprs(value, out):
    if isinstance(value, Expr):
        if value.text:
            out.append(value.text)
    elif isinstance(value, dict):
        for v in value.values():
            _walk_exprs(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _walk_exprs(v, out)


def node_expressions(node):
    """Every verbatim expression attached to a node."""
    out = []
    _walk_exprs(node.op, out)
    _walk_exprs(node.settings, out)
    if node.account is not None and node.account.expr is not None:
        _walk_exprs(node.account.expr, out)
    return out


def _target_root(target):
    """Root field of a targetPath like $Database.LogIntoDB / $['Error ']."""
    if not isinstance(target, str) or not target.startswith("$"):
        return None
    m = _FIELD_Q.match(target)
    if m:
        return m.group(2)
    m = _FIELD.match(target)
    return m.group(1) if m else None


OPEN = None  # open world: field set unknown

# Kinds that pass documents through unchanged (field set preserved).
_PASSTHRU_KINDS = {"filter", "route", "copy", "union", "sort"}


def _out_fields(node, in_fields):
    """Field set on the node's data outputs, given the incoming set."""
    if node.kind in _PASSTHRU_KINDS:
        return in_fields
    if node.kind == "map" and node.op.get("type") == "map":
        if node.op.get("root", "$") != "$":
            return OPEN  # sub-tree mapping: too subtle to model
        targets = set()
        for _, target in node.op["mappings"]:
            root = _target_root(target)
            if root is None and target not in (None, "", "$"):
                return OPEN  # dynamic/unparseable target
            if root:
                targets.add(root)
        if node.op.get("passthrough"):
            return OPEN if in_fields is OPEN else in_fields | targets
        return targets  # passthrough off: only mapped roots survive
    if node.kind == "join":
        return in_fields  # caller passes the union of inputs
    return OPEN  # source/parse/format/call/exec/... : unknown output


def _propagate_fields(pipe):
    """Per-node incoming field set (frozenset or OPEN), in emission order."""
    incoming = {}
    outgoing = {}
    by_id = {n.instance_id: n for n in pipe.nodes}
    in_edges = {}
    for e in pipe.edges:
        in_edges.setdefault(e.dst_id, []).append(e)
    for node in pipe.nodes:  # emission order is topological (order.py)
        edges = in_edges.get(node.instance_id, [])
        if not edges:
            fields = OPEN  # source snap: unknown external schema
        else:
            fields = set()
            for e in edges:
                src = by_id[e.src_id]
                slot = src.slot_by_key.get(e.src_view, e.src_view) or ""
                if slot.startswith("err"):
                    fields = OPEN  # error documents have their own schema
                    break
                up = outgoing.get(e.src_id, OPEN)
                if up is OPEN:
                    fields = OPEN
                    break
                fields |= up
        incoming[node.instance_id] = fields
        outgoing[node.instance_id] = _out_fields(node, fields)
    return incoming


def _check_fields(pipe, findings):
    incoming = _propagate_fields(pipe)
    for node in pipe.nodes:
        known = incoming[node.instance_id]
        if known is OPEN:
            continue
        used = set()
        for text in node_expressions(node):
            used |= field_roots(text)
        # A mapper's own targets are writes, not reads — but reads happen
        # against the incoming document, so no exclusion needed.
        for field in sorted(used - known):
            findings.append(Finding(
                "field-missing", "error", node.ref,
                "reads $%s, but upstream passthrough-off mapping only "
                "provides {%s}" % (field, ", ".join(sorted(known)) or "")))


def _check_params(pipe, findings):
    declared = {p.name: p for p in pipe.params}
    used = {}
    for node in pipe.nodes:
        for text in node_expressions(node):
            for name in param_refs(text):
                used.setdefault(name, []).append((node, text))
    for name in sorted(used):
        if name not in declared:
            for node, _ in used[name][:1]:
                findings.append(Finding(
                    "undeclared-param", "error", node.ref,
                    "references _%s but no parameter %r is declared"
                    % (name, name)))
    for name, param in declared.items():
        if name not in used:
            findings.append(Finding(
                "unused-param", "info", "",
                "parameter %r is never referenced" % name))
        elif param.default is None:
            for node, text in used[name]:
                deref = re.search(r"(?<![\w$.])_%s\s*[.\[]" % re.escape(name),
                                  _strip_strings(text))
                guarded = re.search(
                    r"(?<![\w$.])_%s\s*(==|!=|\?)" % re.escape(name), text) \
                    or "null" in text
                if deref and not guarded:
                    findings.append(Finding(
                        "null-param", "warn", node.ref,
                        "_%s has a null default and is dereferenced without "
                        "a null guard: %s" % (name, text)))


def _check_router(pipe, findings):
    for node in pipe.nodes:
        if node.op.get("type") != "route" or node.op.get("first_match"):
            continue
        exprs = [e.text for e, _ in node.op["routes"]
                 if isinstance(e, Expr) and e.text]
        exhaustive = any(
            other in ("!" + e, "!(%s)" % e)
            for e in exprs for other in exprs)
        if exprs and not exhaustive:
            findings.append(Finding(
                "router-gap", "warn", node.ref,
                "first-match off and no complementary route pair: documents "
                "matching no route are silently dropped"))


def _check_mappings(pipe, findings):
    for node in pipe.nodes:
        if node.op.get("type") != "map":
            continue
        seen = {}
        for _, target in node.op["mappings"]:
            if not target:
                continue
            seen[target] = seen.get(target, 0) + 1
        for target, count in sorted(seen.items()):
            if count > 1:
                findings.append(Finding(
                    "dup-target", "warn", node.ref,
                    "targetPath %s mapped %d times; later rows overwrite "
                    "earlier ones" % (target, count)))


def _check_wiring(pipe, findings):
    has_handler = pipe.error_pipeline is not None
    wired = set()
    for e in pipe.edges:
        wired.add((e.src_id, e.src_view))
        wired.add((e.dst_id, e.dst_view))
    exposed = {(snap_id, key) for _, snap_id, key, _ in pipe.open_views}
    for node in pipe.nodes:
        for port in node.outputs:
            key = (node.instance_id, port.key)
            if key not in wired and key not in exposed:
                findings.append(Finding(
                    "output-unwired", "info", node.ref,
                    "output %s is not connected; its documents are discarded"
                    % port.slot))
        for port in node.errors:
            key = (node.instance_id, port.key)
            if port.behavior == "continue" and key not in wired:
                if has_handler:
                    findings.append(Finding(
                        "error-unwired", "info", node.ref,
                        "error view (%s) unconnected; errors fall through to "
                        "the pipeline-level error handler" % port.slot))
                else:
                    findings.append(Finding(
                        "error-unwired", "warn", node.ref,
                        "errors are routed to the error view (%s) but it is "
                        "not connected and no pipeline-level error handler is "
                        "set — failures vanish silently" % port.slot))


def lint_pipeline(pipe, ir_text=None):
    """Run all checks over an extracted, ordered Pipeline."""
    findings = []
    _check_fields(pipe, findings)
    _check_params(pipe, findings)
    _check_router(pipe, findings)
    _check_mappings(pipe, findings)
    _check_wiring(pipe, findings)
    if ir_text:
        anchors = {}
        for i, line in enumerate(ir_text.splitlines(), 1):
            if line.startswith("node "):
                anchors[line.split()[1]] = i
        for f in findings:
            f.line = anchors.get(f.ref, 0)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (-rank[f.severity], f.line, f.check, f.message))
    return findings


def lint_doc(doc, name_fallback=None):
    """Parse+extract+order a .slp doc, lint it; returns (findings, ir_text)."""
    pipe = parse_slp(doc)
    if not pipe.name and name_fallback:
        pipe.name = name_fallback
        pipe.name_from_filename = True
    for node in pipe.nodes:
        extract(node)
    order_and_mangle(pipe)
    ir_text = emit(pipe)
    return lint_pipeline(pipe, ir_text), ir_text


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pipir-lint", description="Static analysis for pipelines.")
    parser.add_argument("input", help="pipeline export file (.slp)")
    parser.add_argument("--json", action="store_true",
                        help="emit findings as JSON")
    parser.add_argument("--level", choices=SEVERITIES, default="info",
                        help="minimum severity to report (default: info)")
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)
    import os
    findings, _ = lint_doc(
        doc, name_fallback=os.path.splitext(os.path.basename(args.input))[0])
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings = [f for f in findings if rank[f.severity] >= rank[args.level]]

    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        for f in findings:
            where = f.ref or "pipeline"
            loc = ":%d" % f.line if f.line else ""
            print("%-5s %-16s %s%s  %s"
                  % (f.severity.upper(), "[%s]" % f.check, where, loc,
                     f.message))
        print("%d finding(s)" % len(findings))
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
