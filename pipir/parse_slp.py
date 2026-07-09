"""Parse a .slp JSON document into the neutral model (SPEC.md §3–§4, §10).

Handles both observed export variants:
  - older: top-level class_id/class_version + snap_map/link_map/property_map
  - newer: class_fqid/instance_id/instance_version/snap_history/... extras

All platform metadata is dropped here (SPEC §6); what leaves this module is
logic only.
"""

import re

from .kinds import KIND_MNEMONIC, classify
from .model import Account, Edge, Node, Param, Pipeline, Port
from .unwrap import Expr, unwrap

_SNAP_PREFIX = "com-snaplogic-snaps-"
_VIEW_NUM = re.compile(r"(\d+)$")
_PLAIN_VIEW_LABEL = re.compile(r"^(?:input|output|error)\d+$")


class SlpError(ValueError):
    pass


def short_type(class_id):
    if isinstance(class_id, str) and class_id.startswith(_SNAP_PREFIX):
        return class_id[len(_SNAP_PREFIX):]
    return class_id or "unknown"


def _view_sort_key(view_key):
    """Sort view keys by their numeric suffix (input0 < input1 < input101)."""
    m = _VIEW_NUM.search(view_key)
    return (int(m.group(1)) if m else -1, view_key)


def _parse_ports(node, prop_map):
    for section, prefix, dest in (
        ("input", "in", node.inputs),
        ("output", "out", node.outputs),
        ("error", "err", node.errors),
    ):
        views = prop_map.get(section) or {}
        behavior = None
        keys = []
        for key, val in views.items():
            if key == "error_behavior":
                b = unwrap(val)
                behavior = b if isinstance(b, str) else None
                continue
            keys.append((key, val))
        keys.sort(key=lambda kv: _view_sort_key(kv[0]))
        for slot_idx, (key, val) in enumerate(keys):
            view = unwrap(val) if isinstance(val, dict) else {}
            label = view.get("label") if isinstance(view, dict) else None
            if not isinstance(label, str) or _PLAIN_VIEW_LABEL.match(label or ""):
                label = None
            port = Port(
                slot="%s%d" % (prefix, slot_idx),
                key=key,
                label=label,
                binary=(isinstance(view, dict) and view.get("view_type") == "binary"),
                behavior=behavior if prefix == "err" else None,
            )
            dest.append(port)
            node.slot_by_key[key] = port.slot
            if isinstance(view, dict) and isinstance(view.get("label"), str):
                node.slot_by_label.setdefault(view["label"], port.slot)


def _parse_account(prop_map):
    ref = (prop_map.get("account") or {}).get("account_ref")
    if ref is None:
        return None
    val = unwrap(ref)
    if isinstance(val, Expr):
        return Account(expr=val)
    if not isinstance(val, dict) or not val:
        return None
    name = val.get("label")
    type_ = val.get("ref_class_id")
    if name is None and type_ is None:
        return None
    return Account(name=name, type=short_type(type_) if isinstance(type_, str) else type_)


def _parse_snap(instance_id, snap):
    class_id = snap.get("class_id")
    if not class_id and isinstance(snap.get("class_fqid"), str):
        # newer variant: class_fqid = "<class_id>_<version>-<build>"
        class_id = re.sub(r"_\d+.*$", "", snap["class_fqid"])
    native = short_type(class_id)
    kind = classify(native)
    prop_map = snap.get("property_map") or {}
    info = unwrap(prop_map.get("info") or {})
    label = info.get("label")
    if not isinstance(label, str) or not label:
        label = native
    notes = info.get("notes")
    node = Node(
        instance_id=instance_id,
        native=native,
        kind=kind,
        mnemonic=KIND_MNEMONIC[kind],
        label=label,
        notes=notes if isinstance(notes, str) and notes.strip() else None,
    )
    _parse_ports(node, prop_map)
    node.account = _parse_account(prop_map)
    settings = unwrap(prop_map.get("settings") or {})
    if not isinstance(settings, dict):
        settings = {"settings": settings}
    node.settings = settings
    return node


def _parse_params(settings):
    params = []
    for row in unwrap(settings.get("param_table")) or []:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        if not isinstance(key, str) or not key:
            continue
        capture = row.get("capture")
        params.append(Param(name=key, default=row.get("value"),
                            capture=capture is not False))
    return params


def parse_slp(doc):
    if not isinstance(doc, dict):
        raise SlpError("not a JSON object")
    snap_map = doc.get("snap_map")
    if not isinstance(snap_map, dict):
        raise SlpError("no snap_map — not a pipeline export?")

    prop_map = doc.get("property_map") or {}
    info = unwrap(prop_map.get("info") or {})
    name = info.get("label")
    settings = prop_map.get("settings") or {}

    pipe = Pipeline(name=name if isinstance(name, str) else "")
    pipe.params = _parse_params(settings)
    pipe.imports = [i for i in (unwrap(settings.get("imports")) or [])
                    if isinstance(i, (str, Expr))]
    err_pipe = unwrap(settings.get("error_pipeline"))
    if err_pipe:
        pipe.error_pipeline = err_pipe
        for row in unwrap(settings.get("error_param_table")) or []:
            if isinstance(row, dict) and row.get("key") is not None:
                pipe.error_args.append((row.get("key"), row.get("value")))
    err = prop_map.get("error")
    if isinstance(err, dict) and "error_behavior" in err:
        b = unwrap(err["error_behavior"])
        if isinstance(b, str):
            pipe.error_behavior = b

    for instance_id in snap_map:
        pipe.nodes.append(_parse_snap(instance_id, snap_map[instance_id]))

    for link in (doc.get("link_map") or {}).values():
        if not isinstance(link, dict):
            continue
        pipe.edges.append(Edge(
            src_id=link.get("src_id"), src_view=link.get("src_view_id"),
            dst_id=link.get("dst_id"), dst_view=link.get("dst_view_id"),
        ))

    # Pipeline-level i/o: property_map.input / .output keyed "<snap-instance>_<viewkey>"
    for direction, section in (("in", "input"), ("out", "output")):
        views = prop_map.get(section) or {}
        for key, val in views.items():
            if key == "error_behavior" or not isinstance(val, dict):
                continue
            view = unwrap(val)
            label = view.get("label") if isinstance(view, dict) else None
            snap_id, sep, view_key = key.rpartition("_")
            if sep:
                pipe.open_views.append(
                    (direction, snap_id, view_key,
                     label if isinstance(label, str) else None))
    return pipe
