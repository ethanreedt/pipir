"""Top-level conversion: parsed .slp JSON -> canonical IR text."""

from .emit import emit
from .extract import extract
from .order import order_and_mangle
from .parse_slp import parse_slp


def build_pipeline(doc, name_fallback=None):
    """Parse, extract, and order: the shared front half of every consumer."""
    pipe = parse_slp(doc)
    if not pipe.name and name_fallback:
        pipe.name = name_fallback
        pipe.name_from_filename = True
    for node in pipe.nodes:
        extract(node)
    order_and_mangle(pipe)
    return pipe


def convert_slp(doc, name_fallback=None):
    return emit(build_pipeline(doc, name_fallback))


def idmap(pipe):
    """Glue map for tooling: mangled ref -> stable .slp instance_id."""
    return {n.ref: n.instance_id for n in pipe.nodes}
