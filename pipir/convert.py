"""Top-level conversion: parsed .slp JSON -> canonical IR text."""

from .emit import emit
from .extract import extract
from .order import order_and_mangle
from .parse_slp import parse_slp


def convert_slp(doc, name_fallback=None):
    pipe = parse_slp(doc)
    if not pipe.name and name_fallback:
        pipe.name = name_fallback
        pipe.name_from_filename = True
    for node in pipe.nodes:
        extract(node)
    order_and_mangle(pipe)
    return emit(pipe)
