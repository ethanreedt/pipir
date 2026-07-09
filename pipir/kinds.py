"""class_id -> neutral kind classification (SPEC.md §7).

Keys are the short native type: class_id minus the com-snaplogic-snaps- prefix.
Unknown types fall back to ("opaque", "op") — preserve-and-flag, never guess.
"""

KIND_MNEMONIC = {
    "map": "map",
    "route": "route",
    "filter": "filter",
    "join": "join",
    "union": "union",
    "copy": "copy",
    "sort": "sort",
    "aggregate": "agg",
    "parse": "parse",
    "format": "format",
    "source": "read",
    "sink": "write",
    "call": "call",
    "exec": "exec",
    "script": "script",
    "effect": "effect",
    "opaque": "op",
}

_KIND_BY_TYPE = {
    "transform-datatransform": "map",
    "flow-router": "route",
    "transform-router": "route",
    "flow-filter": "filter",
    "transform-multijoin": "join",
    "transform-join": "join",
    "flow-union": "union",
    "flow-copy": "copy",
    "transform-sort": "sort",
    "transform-aggregate": "aggregate",
    "transform-groupbyfields": "aggregate",
    "transform-csvparser": "parse",
    "transform-jsonparser": "parse",
    "transform-xmlparser": "parse",
    "transform-excelparser": "parse",
    "transform-binarytodocument": "parse",
    "transform-csvformatter": "format",
    "transform-jsonformatter": "format",
    "transform-xmlformatter": "format",
    "transform-documenttobinary": "format",
    "binary-simpleread": "source",
    "binary-multifilereader": "source",
    "email-emailreader": "source",
    "jms-jmsconsumer": "source",
    "binary-simplewrite": "sink",
    "binary-write": "sink",
    "email-emailsender": "sink",
    "blackberry-postfile": "sink",
    "jms-jmsproducer": "sink",
    "rest-get": "call",
    "rest-post": "call",
    "rest-put": "call",
    "rest-delete": "call",
    "flow-pipeexec": "exec",
    "script-script": "script",
    "binary-delete": "effect",
}


def classify(native: str) -> str:
    """Map a short native type to a neutral kind."""
    kind = _KIND_BY_TYPE.get(native)
    if kind:
        return kind
    # DB "Execute" family (generic JDBC / MySQL / Oracle / ...): arbitrary SQL,
    # request/response shaped -> call (SPEC §7).
    if native.endswith("-execute"):
        return "call"
    return "opaque"
