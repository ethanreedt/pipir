"""GitHub-style diff rows between two IR texts, with node pairing.

Rows: {"t": "ctx"|"add"|"del"|"gap", "an": int|None, "bn": int|None, "s": str}
The optional idmap pair (ref -> instance_id for each side) lets callers map
renumbered node ids; used by the PR view where both .slp versions exist.
"""

import difflib


def diff_rows(a_text, b_text, context=3):
    a = a_text.splitlines()
    b = b_text.splitlines()
    rows = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for group in matcher.get_grouped_opcodes(context):
        if rows:
            rows.append({"t": "gap", "an": None, "bn": None, "s": ""})
        for tag, i1, i2, j1, j2 in group:
            if tag in ("equal",):
                for k in range(i2 - i1):
                    rows.append({"t": "ctx", "an": i1 + k + 1,
                                 "bn": j1 + k + 1, "s": a[i1 + k]})
            else:
                for k in range(i1, i2):
                    rows.append({"t": "del", "an": k + 1, "bn": None,
                                 "s": a[k]})
                for k in range(j1, j2):
                    rows.append({"t": "add", "an": None, "bn": k + 1,
                                 "s": b[k]})
    return rows


def stats(rows):
    return {"add": sum(1 for r in rows if r["t"] == "add"),
            "del": sum(1 for r in rows if r["t"] == "del")}


def renames(idmap_a, idmap_b):
    """Nodes whose stable instance_id survived but whose ref changed."""
    by_uuid_a = {v: k for k, v in idmap_a.items()}
    out = []
    for ref_b, uuid in idmap_b.items():
        ref_a = by_uuid_a.get(uuid)
        if ref_a and ref_a != ref_b:
            out.append({"from": ref_a, "to": ref_b})
    return sorted(out, key=lambda r: r["to"])
