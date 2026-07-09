"""Lint engine tests, driven by small synthetic .slp documents."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipir.lint import lint_doc


def wrap(v):
    return {"value": v}


def expr(text):
    return {"expression": True, "value": text}


def snap(class_id, label, settings, uid, n_in=1, n_out=1, err="fail"):
    pm = {
        "info": {"label": wrap(label)},
        "settings": settings,
        "error": {"error0": {"label": wrap("error0"),
                             "view_type": wrap("document")},
                  "error_behavior": wrap(err)},
    }
    if n_in:
        pm["input"] = {"input%d" % i: {"label": wrap("input%d" % i),
                                       "view_type": wrap("document")}
                       for i in range(n_in)}
    if n_out:
        pm["output"] = {"output%d" % i: {"label": wrap("output%d" % i),
                                         "view_type": wrap("document")}
                        for i in range(n_out)}
    return {"class_id": class_id, "instance_id": uid, "property_map": pm}


def mapper(uid, label, mappings, passthrough=False):
    table = [{"expression": expr(e), "targetPath": wrap(t)}
             for e, t in mappings]
    return snap("com-snaplogic-snaps-transform-datatransform", label, {
        "passThrough": wrap(passthrough),
        "nullSafeAccess": wrap(False),
        "transformations": wrap({"mappingRoot": wrap("$"),
                                 "mappingTable": wrap(table)}),
    }, uid)


def doc(snaps, links, params=()):
    return {
        "class_id": "com-snaplogic-pipeline",
        "class_version": 8,
        "property_map": {
            "info": {"label": wrap("test")},
            "settings": {"param_table": wrap([
                {"capture": wrap(True), "key": wrap(p), "value": wrap(None)}
                for p in params])},
        },
        "snap_map": {s["instance_id"]: s for s in snaps},
        "link_map": {"link%d" % i: {
            "src_id": a, "src_view_id": av, "dst_id": b, "dst_view_id": bv}
            for i, (a, av, b, bv) in enumerate(links)},
    }


def checks(findings):
    return {f.check for f in findings}


class LintTests(unittest.TestCase):
    def test_passthrough_kill(self):
        d = doc([
            mapper("u1", "set fields", [("_p", "$a")]),
            snap("com-snaplogic-snaps-flow-filter", "F",
                 {"filterExpression": expr("$b == 1")}, "u2"),
        ], [("u1", "output0", "u2", "input0")], params=["p"])
        findings, _ = lint_doc(d)
        self.assertIn("field-missing", checks(findings))
        msgs = [f.message for f in findings if f.check == "field-missing"]
        self.assertIn("$b", msgs[0])

    def test_passthrough_on_is_open_world(self):
        d = doc([
            mapper("u1", "set fields", [("_p", "$a")], passthrough=True),
            snap("com-snaplogic-snaps-flow-filter", "F",
                 {"filterExpression": expr("$b == 1")}, "u2"),
        ], [("u1", "output0", "u2", "input0")], params=["p"])
        findings, _ = lint_doc(d)
        self.assertNotIn("field-missing", checks(findings))

    def test_undeclared_and_unused_param(self):
        d = doc([mapper("u1", "m", [("_typo", "$a")])],
                [], params=["real"])
        findings, _ = lint_doc(d)
        self.assertIn("undeclared-param", checks(findings))
        self.assertIn("unused-param", checks(findings))

    def test_null_param_deref(self):
        d = doc([mapper("u1", "m", [("_p.trim()", "$a")])],
                [], params=["p"])
        findings, _ = lint_doc(d)
        self.assertIn("null-param", checks(findings))

    def test_null_param_guarded(self):
        d = doc([mapper("u1", "m",
                        [("_p != null ? _p.trim() : \"\"", "$a")])],
                [], params=["p"])
        findings, _ = lint_doc(d)
        self.assertNotIn("null-param", checks(findings))

    def test_router_gap_and_complement(self):
        router = snap("com-snaplogic-snaps-flow-router", "R", {
            "firstMatch": wrap(False),
            "routes": wrap([
                {"expression": expr("$x == 1"),
                 "outputViewName": wrap("output0")},
                {"expression": expr("$x == 2"),
                 "outputViewName": wrap("output1")},
            ])}, "u1", n_out=2)
        findings, _ = lint_doc(doc([router], []))
        self.assertIn("router-gap", checks(findings))

        router["property_map"]["settings"]["routes"] = wrap([
            {"expression": expr("$x == 1"), "outputViewName": wrap("output0")},
            {"expression": expr("!$x == 1"), "outputViewName": wrap("output1")},
        ])
        findings, _ = lint_doc(doc([router], []))
        self.assertNotIn("router-gap", checks(findings))

    def test_dup_target(self):
        d = doc([mapper("u1", "m", [("1", "$a"), ("2", "$a")])], [])
        findings, _ = lint_doc(d)
        self.assertIn("dup-target", checks(findings))

    def test_error_unwired(self):
        d = doc([mapper("u1", "m", [("1", "$a")])], [])
        d["snap_map"]["u1"]["property_map"]["error"]["error_behavior"] = \
            wrap("continue")
        findings, _ = lint_doc(d)
        self.assertIn("error-unwired", checks(findings))

    def test_line_anchor(self):
        d = doc([mapper("u1", "m", [("_typo", "$a")])], [])
        findings, ir_text = lint_doc(d)
        f = [x for x in findings if x.check == "undeclared-param"][0]
        self.assertTrue(
            ir_text.splitlines()[f.line - 1].startswith("node " + f.ref))

    def test_real_fixture_finds_typo(self):
        import json
        path = os.path.join(ROOT, "fixtures", "real",
                            "sub_INT8000_QV_RPT_WS.slp")
        with open(path, encoding="utf-8") as fh:
            findings, _ = lint_doc(json.load(fh))
        undeclared = [f for f in findings if f.check == "undeclared-param"]
        self.assertEqual(len(undeclared), 1)
        self.assertIn("_ToEmail", undeclared[0].message)


if __name__ == "__main__":
    unittest.main()
