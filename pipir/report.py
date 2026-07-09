"""Coverage report: which snap types hit typed extractors vs. fallback."""

from .extract import _EXTRACTORS
from .kinds import classify
from .parse_slp import parse_slp


def coverage(doc):
    """Return rows of (native_type, kind, tier, count) for one parsed .slp."""
    pipe = parse_slp(doc)
    counts = {}
    for node in pipe.nodes:
        counts[node.native] = counts.get(node.native, 0) + 1
    rows = []
    for native in sorted(counts):
        kind = classify(native)
        if kind in _EXTRACTORS:
            tier = "typed"
        elif kind == "opaque":
            tier = "opaque"
        else:
            tier = "classified"
        rows.append((native, kind, tier, counts[native]))
    return rows


def format_coverage(rows):
    lines = ["%-45s %-10s %-10s %s" % ("native type", "kind", "tier", "count")]
    for native, kind, tier, count in rows:
        lines.append("%-45s %-10s %-10s %d" % (native, kind, tier, count))
    tiers = {}
    for _, _, tier, count in rows:
        tiers[tier] = tiers.get(tier, 0) + count
    total = sum(tiers.values()) or 1
    summary = ", ".join("%s %d/%d" % (t, tiers.get(t, 0), total)
                        for t in ("typed", "classified", "opaque"))
    lines.append("")
    lines.append("snaps: " + summary)
    return "\n".join(lines) + "\n"
