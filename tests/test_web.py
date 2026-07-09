"""Web-layer tests: graph building, content hashes, diff rows."""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipir.web.diffing import diff_rows, renames, stats
from pipir.web.graph import build_graph

REAL = os.path.join(ROOT, "fixtures", "real")


def load(name):
    with open(os.path.join(REAL, name), encoding="utf-8") as f:
        return json.load(f)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = build_graph(load("sub_INT8000_QV_RPT_WS.slp"),
                                 name_fallback="X")

    def test_shape(self):
        g = self.graph
        self.assertEqual(len(g["nodes"]), 30)
        self.assertEqual(len(g["edges"]), 36)
        refs = {n["ref"] for n in g["nodes"]}
        for e in g["edges"]:
            self.assertIn(e["src"], refs)
            self.assertIn(e["dst"], refs)

    def test_blocks_cover_all_nodes(self):
        for n in self.graph["nodes"]:
            self.assertTrue(n["block"].startswith("node %s " % n["ref"]),
                            n["ref"])
            self.assertEqual(
                self.graph["ir"].splitlines()[n["line"] - 1],
                n["block"].splitlines()[0])

    def test_error_edges_flagged(self):
        self.assertTrue(any(e["error"] for e in self.graph["edges"]))

    def test_layout_no_overlap(self):
        seen = set()
        for n in self.graph["nodes"]:
            self.assertNotIn((n["x"], n["y"]), seen)
            seen.add((n["x"], n["y"]))

    def test_hash_ignores_ordinal(self):
        # Same node content under a different mangled ref hashes identically.
        from pipir.web.graph import content_hash
        block = "node map.3 map native=t\n  label \"L\"\n  map expr \"1\" -> \"$a\""
        block2 = block.replace("map.3", "map.7")
        self.assertEqual(content_hash("map.3", block),
                         content_hash("map.7", block2))


class DiffTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(diff_rows("a\nb\n", "a\nb\n"), [])

    def test_basic(self):
        rows = diff_rows("a\nb\nc\n", "a\nX\nc\n")
        kinds = [r["t"] for r in rows]
        self.assertIn("del", kinds)
        self.assertIn("add", kinds)
        s = stats(rows)
        self.assertEqual((s["add"], s["del"]), (1, 1))

    def test_renames(self):
        a = {"map.1": "u1", "map.2": "u2"}
        b = {"map.2": "u1", "map.3": "u2"}
        out = renames(a, b)
        self.assertEqual(out, [{"from": "map.1", "to": "map.2"},
                               {"from": "map.2", "to": "map.3"}])


if __name__ == "__main__":
    unittest.main()
