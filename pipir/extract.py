"""Typed extractors (SPEC.md §7): promote well-understood settings into
dedicated statements, leaving the remainder for generic `set` lines.

Each extractor mutates node.statements and pops the settings it consumed.
Extraction is defensive: if a setting doesn't have the expected shape, it is
left in node.settings rather than half-parsed — nothing is ever dropped.
"""

from .emit import render_value
from .unwrap import Expr


def _pop_rows(node, key):
    rows = node.settings.get(key)
    if isinstance(rows, list) and all(isinstance(r, dict) for r in rows):
        node.settings.pop(key)
        return rows
    return None


def _slot(node, view_name):
    """Resolve a native view reference (key or label) to a canonical slot."""
    if not isinstance(view_name, str):
        return None
    return node.slot_by_key.get(view_name) or node.slot_by_label.get(view_name)


def _extract_map(node):
    trans = node.settings.get("transformations")
    if not isinstance(trans, dict):
        return
    table = trans.get("mappingTable")
    if not (isinstance(table, list) and all(isinstance(r, dict) for r in table)):
        return
    node.settings.pop("transformations")
    stmts = []
    root = trans.get("mappingRoot")
    if isinstance(root, str) and root != "$":
        stmts.append("root " + render_value(root))
    if node.settings.pop("passThrough", False) is True:
        stmts.append("passthrough on")
    if node.settings.pop("nullSafeAccess", False) is True:
        stmts.append("nullsafe on")
    for row in table:
        expr = render_value(row.get("expression"))
        target = row.get("targetPath")
        if target is None or target == "":
            stmts.append("map %s ->" % expr)
        else:
            stmts.append("map %s -> %s" % (expr, render_value(target)))
        extra = {k: v for k, v in row.items()
                 if k not in ("expression", "targetPath") and v is not None}
        for k in sorted(extra):
            stmts.append("  %s %s" % (k, render_value(extra[k])))
    leftovers = {k: v for k, v in trans.items()
                 if k not in ("mappingTable", "mappingRoot")}
    for k, v in leftovers.items():
        node.settings["transformations." + k] = v
    node.statements = stmts


def _extract_route(node):
    routes = _pop_rows(node, "routes")
    if routes is None:
        return
    first = node.settings.pop("firstMatch", None)
    stmts = ["first-match " + ("on" if first is True else "off")]
    if not routes:
        # Documented Router behavior with an empty routes table.
        stmts.append("; no routes: documents round-robin across outputs")
    for row in routes:
        target = _slot(node, row.get("outputViewName")) \
            or render_value(row.get("outputViewName"))
        stmts.append("when %s -> %s" % (render_value(row.get("expression")), target))
    node.statements = stmts


def _extract_filter(node):
    expr = node.settings.pop("filterExpression", None)
    if expr is None:
        return
    stmts = ["where " + render_value(expr)]
    if node.settings.pop("nullSafeAccess", False) is True:
        stmts.append("nullsafe on")
    node.statements = stmts


def _extract_join(node):
    paths = _pop_rows(node, "joinPaths")
    if paths is None:
        return
    stmts = []
    jtype = node.settings.pop("joinType", None)
    if isinstance(jtype, str):
        stmts.append("join " + jtype.lower().replace(" ", "-"))
    for row in paths:
        right_view = _slot(node, row.get("rightInputView")) \
            or render_value(row.get("rightInputView"))
        stmts.append("on %s == %s %s" % (
            render_value(row.get("leftPath")), right_view,
            render_value(row.get("rightPath"))))
    node.statements = stmts


def _extract_exec(node):
    pipeline = node.settings.pop("pipeline", None)
    if pipeline is None:
        return
    stmts = ["call " + render_value(pipeline)]
    params = node.settings.get("params")
    if isinstance(params, list) and all(isinstance(r, dict) for r in params):
        node.settings.pop("params")
        for row in params:
            key = row.get("key")
            key = key if isinstance(key, str) else render_value(key)
            stmts.append("arg %s %s" % (key, render_value(row.get("value"))))
    node.statements = stmts


_EXTRACTORS = {
    "map": _extract_map,
    "route": _extract_route,
    "filter": _extract_filter,
    "join": _extract_join,
    "exec": _extract_exec,
}


def extract(node):
    fn = _EXTRACTORS.get(node.kind)
    if fn:
        fn(node)
