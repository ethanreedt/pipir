"""The .slp value/expression wrapper convention (SPEC.md §8).

Almost every leaf in a .slp property_map is wrapped:

    {"value": X}                        -> literal X
    {"expression": false, "value": X}   -> literal X
    {"expression": true,  "value": "E"} -> Expr("E"), a verbatim expression string
    {"expression": true}                -> Expr(None)

Unwrapping is recursive: wrappers nest (mappingTable rows, account-ref fields).
A dict that is not wrapper-shaped is kept, with its values unwrapped.
"""

_WRAPPER_KEYS = {"expression", "value"}


class Expr:
    """A verbatim SnapLogic expression string (or None for the empty-value case)."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text  # str | None

    def __repr__(self):
        return "Expr(%r)" % (self.text,)

    def __eq__(self, other):
        return isinstance(other, Expr) and other.text == self.text

    def __hash__(self):
        return hash(("Expr", self.text))


def unwrap(value):
    """Recursively strip value/expression wrappers, marking expressions with Expr."""
    if isinstance(value, dict):
        keys = set(value)
        if keys and keys <= _WRAPPER_KEYS:
            if value.get("expression"):
                inner = value.get("value")
                # Expression payloads are strings; null/absent means "empty".
                return Expr(inner) if isinstance(inner, str) else Expr(None)
            return unwrap(value.get("value"))
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v) for v in value]
    return value
