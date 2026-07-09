"""pipir test harness (Phase 3).

    python -m unittest discover tests           # run
    PIPIR_REGEN=1 python -m unittest discover tests   # regenerate goldens

Golden files live in fixtures/golden/<name>.pipir, one per fixture in
fixtures/real/. Determinism tests apply cosmetic mutations to each fixture
and assert byte-identical IR (SPEC.md §9).
"""

import difflib
import json
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipir.convert import convert_slp
from pipir.unwrap import Expr, unwrap

REAL = os.path.join(ROOT, "fixtures", "real")
GOLDEN = os.path.join(ROOT, "fixtures", "golden")
REGEN = os.environ.get("PIPIR_REGEN") == "1"


def fixtures():
    return sorted(f for f in os.listdir(REAL) if f.endswith(".slp"))


def load(name):
    with open(os.path.join(REAL, name), "r", encoding="utf-8") as f:
        return json.load(f)


def ir_for(name):
    return convert_slp(load(name), name_fallback=os.path.splitext(name)[0])


class GoldenTests(unittest.TestCase):
    """Converter output matches the committed golden files."""

    maxDiff = None

    def test_goldens(self):
        os.makedirs(GOLDEN, exist_ok=True)
        for name in fixtures():
            with self.subTest(fixture=name):
                got = ir_for(name)
                golden_path = os.path.join(
                    GOLDEN, os.path.splitext(name)[0] + ".pipir")
                if REGEN or not os.path.exists(golden_path):
                    with open(golden_path, "w", encoding="utf-8",
                              newline="\n") as f:
                        f.write(got)
                    continue
                with open(golden_path, "r", encoding="utf-8", newline="") as f:
                    want = f.read()
                if got != want:
                    diff = "\n".join(difflib.unified_diff(
                        want.splitlines(), got.splitlines(),
                        "golden", "converted", lineterm=""))
                    self.fail("IR differs from golden %s:\n%s"
                              % (golden_path, diff))


def _shuffle_keys(obj, rng):
    if isinstance(obj, dict):
        items = list(obj.items())
        rng.shuffle(items)
        return {k: _shuffle_keys(v, rng) for k, v in items}
    if isinstance(obj, list):
        return [_shuffle_keys(v, rng) for v in obj]
    return obj


class DeterminismTests(unittest.TestCase):
    """Cosmetic .slp mutations must not change a single output byte."""

    def check(self, mutate):
        for name in fixtures():
            with self.subTest(fixture=name):
                doc = load(name)
                base = convert_slp(doc, name_fallback="X")
                mutated = mutate(json.loads(json.dumps(doc)), random.Random(7))
                self.assertEqual(
                    convert_slp(mutated, name_fallback="X"), base)

    def test_object_key_order(self):
        self.check(lambda doc, rng: _shuffle_keys(doc, rng))

    def test_snap_map_order(self):
        def mutate(doc, rng):
            items = list(doc["snap_map"].items())
            rng.shuffle(items)
            doc["snap_map"] = dict(items)
            return doc
        self.check(mutate)

    def test_link_renumbering_and_order(self):
        def mutate(doc, rng):
            links = list((doc.get("link_map") or {}).values())
            rng.shuffle(links)
            doc["link_map"] = {"link%d" % (900000 - i * 13): l
                               for i, l in enumerate(links)}
            return doc
        self.check(mutate)

    def test_render_map_removed(self):
        def mutate(doc, rng):
            doc.pop("render_map", None)
            return doc
        self.check(mutate)

    def test_render_map_perturbed(self):
        def mutate(doc, rng):
            doc["render_map"] = {"pan": [rng.random(), rng.random()],
                                 "zoom": rng.random()}
            return doc
        self.check(mutate)

    def test_volatile_export_metadata(self):
        def mutate(doc, rng):
            doc.pop("snap_history", None)
            for key in ("instance_version", "link_serial", "snode_id"):
                if key in doc:
                    doc[key] = "mutated-%d" % rng.randrange(10 ** 6)
            for snap in doc["snap_map"].values():
                if "instance_version" in snap:
                    snap["instance_version"] = rng.randrange(10 ** 6)
                if "class_build_tag" in snap:
                    snap["class_build_tag"] = "build-%d" % rng.randrange(100)
            return doc
        self.check(mutate)

    def test_reserialization(self):
        self.check(lambda doc, rng: json.loads(
            json.dumps(doc, indent=3, sort_keys=True)))


class UnwrapTests(unittest.TestCase):
    def test_plain_value(self):
        self.assertEqual(unwrap({"value": 5}), 5)

    def test_literal_flag(self):
        self.assertEqual(unwrap({"expression": False, "value": "x"}), "x")

    def test_expression(self):
        self.assertEqual(unwrap({"expression": True, "value": "_p"}),
                         Expr("_p"))

    def test_expression_no_value(self):
        self.assertEqual(unwrap({"expression": True}), Expr(None))
        self.assertEqual(unwrap({"expression": True, "value": None}),
                         Expr(None))

    def test_nested(self):
        wrapped = {"value": [{"k": {"expression": True, "value": "$f"}}]}
        self.assertEqual(unwrap(wrapped), [{"k": Expr("$f")}])

    def test_non_wrapper_dict_preserved(self):
        self.assertEqual(unwrap({"a": {"value": 1}, "b": 2}),
                         {"a": 1, "b": 2})


if __name__ == "__main__":
    unittest.main()
