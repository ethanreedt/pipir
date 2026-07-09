"""pipir web — local website for browsing, diffing, and analyzing pipelines.

    python -m pipir.web [root_dir] [--port 8642]

Serves .slp files found under root_dir (recursively). Stdlib only.
"""

import argparse
import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..convert import build_pipeline, idmap
from ..emit import emit
from ..lint import lint_pipeline
from . import diffing, gitpr, llm, notes
from .graph import build_graph

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class State:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._cache = {}          # relpath -> (mtime, graph)
        self._lock = threading.Lock()

    def list_files(self):
        out = []
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d != "__pycache__"]
            for f in sorted(files):
                if f.endswith(".slp"):
                    out.append(os.path.relpath(os.path.join(base, f),
                                               self.root))
        return sorted(out)

    def _resolve(self, rel):
        path = os.path.abspath(os.path.join(self.root, rel))
        if not path.startswith(self.root + os.sep) and path != self.root:
            raise ApiError("path outside served root", 403)
        if not os.path.isfile(path):
            raise ApiError("no such file: %s" % rel, 404)
        return path

    def doc(self, rel):
        with open(self._resolve(rel), "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except ValueError as exc:
                raise ApiError("%s is not valid JSON: %s" % (rel, exc))

    def graph(self, rel):
        path = self._resolve(rel)
        mtime = os.stat(path).st_mtime
        with self._lock:
            hit = self._cache.get(rel)
            if hit and hit[0] == mtime:
                return hit[1]
        stem = os.path.splitext(os.path.basename(rel))[0]
        graph = build_graph(self.doc(rel), name_fallback=stem)
        with self._lock:
            self._cache[rel] = (mtime, graph)
        return graph


def _convert_side(doc, stem):
    pipe = build_pipeline(doc, name_fallback=stem)
    ir = emit(pipe)
    return ir, idmap(pipe), lint_pipeline(pipe, ir)


def _new_findings(base_findings, head_findings):
    """Findings present on head but not base, matched check+message
    (refs renumber across versions, so they can't be part of the key)."""
    seen = {(f.check, f.message) for f in base_findings}
    return [f.__dict__ for f in head_findings
            if (f.check, f.message) not in seen]


def _pr_payload(state, repo, number):
    base, head, paths = gitpr.pr_slp_files(repo, number)
    files = []
    for path in paths:
        stem = os.path.splitext(os.path.basename(path))[0]
        pair = []
        for rev in (base, head):
            raw = gitpr.blob(repo, rev, path)
            if raw is None:
                pair.append(("", {}, []))
                continue
            try:
                pair.append(_convert_side(json.loads(raw), stem))
            except ValueError:
                pair.append((raw, {}, []))  # not JSON: diff raw text
        (a_ir, a_map, a_lint), (b_ir, b_map, b_lint) = pair
        rows = diffing.diff_rows(a_ir, b_ir)
        files.append({
            "path": path,
            "rows": rows,
            "stats": diffing.stats(rows),
            "renames": diffing.renames(a_map, b_map),
            "new_findings": _new_findings(a_lint, b_lint),
        })
    return {"base": base[:12], "head": head[:12], "files": files}


class Handler(BaseHTTPRequestHandler):
    state = None  # set by serve()

    def log_message(self, fmt, *args):
        sys.stderr.write("pipir-web: %s\n" % (fmt % args))

    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else \
            json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api(self, fn):
        try:
            self._send(200, fn())
        except ApiError as exc:
            self._send(exc.status, {"error": str(exc)})
        except (llm.LlmError, gitpr.GitError) as exc:
            self._send(502, {"error": str(exc)})
        except Exception as exc:  # surface, don't kill the thread
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        state = self.state
        if url.path == "/api/list":
            self._api(lambda: {"files": state.list_files(),
                               "llm": llm.configured()})
        elif url.path == "/api/graph":
            def go():
                graph = dict(state.graph(q["f"]))
                graph["annotations"] = notes.for_graph(state.root, graph)
                return graph
            self._api(go)
        elif url.path == "/api/pr":
            self._api(lambda: _pr_payload(state, q["repo"], int(q["n"])))
        elif url.path in ("/", "/index.html"):
            self._static("index.html")
        else:
            self._static(url.path.lstrip("/"))

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": "invalid JSON body"})
            return
        state = self.state
        if url.path == "/api/chat":
            def go():
                graph = state.graph(body["f"])
                lint_ctx = "\n".join(
                    "%s [%s] %s: %s" % (f["severity"], f["check"],
                                        f["ref"] or "pipeline", f["message"])
                    for f in graph["findings"]) or "none"
                system = (
                    "You answer questions about one ETL pipeline, given its "
                    "ETL-IR text (an assembly-like format: node blocks with "
                    "mapping/route/join statements, edge lines wiring ports, "
                    "expressions kept verbatim from the source platform). "
                    "Be concrete; cite node ids like map.3.\n\nPipeline "
                    "'%s':\n\n%s\n\nStatic-analysis findings:\n%s"
                    % (graph["name"], graph["ir"], lint_ctx))
                messages = [{"role": "system", "content": system}]
                messages += [m for m in body.get("messages", [])
                             if m.get("role") in ("user", "assistant")]
                return {"reply": llm.chat(messages)}
            self._api(go)
        elif url.path == "/api/annotate":
            def go():
                graph = state.graph(body["f"])
                return {"annotations": notes.annotate(state.root, graph)}
            self._api(go)
        else:
            self._send(404, {"error": "unknown endpoint"})

    def _static(self, name):
        path = os.path.abspath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            self._send(404, {"error": "not found"})
            return
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, MIME.get(os.path.splitext(path)[1],
                                       "application/octet-stream"))


def serve(root, port):
    llm.load_env(root)
    llm.load_env(os.getcwd())
    Handler.state = State(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("pipir web: serving %s at http://127.0.0.1:%d" % (root, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pipir-web", description="Local pipeline browser.")
    parser.add_argument("root", nargs="?", default=".",
                        help="directory containing .slp files (default: .)")
    parser.add_argument("--port", type=int, default=8642)
    args = parser.parse_args(argv)
    serve(args.root, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
