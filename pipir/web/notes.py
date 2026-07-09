"""LLM node annotations, cached in a sidecar keyed by node content hash.

The sidecar (.pipir-notes.json in the served root) maps content hashes to
short notes, so annotations survive regeneration and node renumbering and
self-invalidate when a node's logic changes.
"""

import json
import os
import re
import threading

from . import llm

_LOCK = threading.Lock()
SIDECAR = ".pipir-notes.json"

_PROMPT = (
    "You are annotating an ETL pipeline written in ETL-IR, an assembly-like "
    "text format: `node <id> <kind> native=<type>` blocks with mapping/route/"
    "join statements and verbatim settings, followed by `edge` lines wiring "
    "node ports.\n\n"
    "For EVERY node in the pipeline below, write one note of at most 12 "
    "words stating what the node does in this pipeline (its purpose, not "
    "its type). Respond with ONLY a JSON object mapping node id to note, "
    'e.g. {"map.1": "sets logging flags from pipeline parameters"}.\n\n'
)


def _path(root):
    return os.path.join(root, SIDECAR)


def load(root):
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(root, notes):
    with open(_path(root), "w", encoding="utf-8") as f:
        json.dump(notes, f, indent=2, sort_keys=True)
        f.write("\n")


def for_graph(root, graph):
    """Cached annotations for a graph: {ref: note}."""
    notes = load(root)
    return {n["ref"]: notes[n["hash"]] for n in graph["nodes"]
            if n["hash"] in notes}


def annotate(root, graph):
    """Fill missing annotations via the LLM; returns {ref: note}."""
    with _LOCK:
        notes = load(root)
        missing = [n for n in graph["nodes"] if n["hash"] not in notes]
        if missing:
            reply = llm.chat([
                {"role": "user",
                 "content": _PROMPT + graph["ir"]},
            ], max_tokens=80 * len(graph["nodes"]) + 400)
            m = re.search(r"\{.*\}", reply, re.S)
            if not m:
                raise llm.LlmError(
                    "LLM did not return a JSON object: %s" % reply[:200])
            by_ref = json.loads(m.group(0))
            hash_by_ref = {n["ref"]: n["hash"] for n in graph["nodes"]}
            for ref, note in by_ref.items():
                if ref in hash_by_ref and isinstance(note, str):
                    notes[hash_by_ref[ref]] = note.strip()
            _save(root, notes)
    return {n["ref"]: notes[n["hash"]] for n in graph["nodes"]
            if n["hash"] in notes}
