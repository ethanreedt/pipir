"use strict";
const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";

async function api(path, opts) {
  const resp = await fetch(path, opts);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || resp.statusText);
  return data;
}
function setMsg(el, text, isError) {
  el.textContent = text || "";
  el.classList.toggle("error", !!isError);
}
function el(tag, attrs, text) {
  const node = document.createElement(tag);
  for (const k in attrs || {}) node.setAttribute(k, attrs[k]);
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---------- tabs ---------- */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
  };
});

/* ---------- file lists ---------- */
let FILES = [], LLM_OK = false;
async function loadFiles() {
  const data = await api("/api/list");
  FILES = data.files; LLM_OK = data.llm;
  for (const sel of [$("file-select"), $("chat-file")]) {
    sel.innerHTML = "";
    FILES.forEach((f) => sel.appendChild(el("option", { value: f }, f)));
  }
  if (!LLM_OK) {
    $("annotate-btn").disabled = true;
    $("annotate-btn").title = "Set PIPIR_LLM_BASE_URL in .env to enable";
  }
  if (FILES.length) {
    $("file-select").value = FILES[0];
    loadPipeline(FILES[0]);
  }
}

/* ---------- pipeline view ---------- */
let GRAPH = null, SELECTED = null;
const view = { x: 0, y: 0, k: 1 };

function portY(list, slot, h) {
  const i = Math.max(0, list.indexOf(slot));
  return ((i + 1) * h) / (list.length + 1);
}
function nodeBadges(n) {
  const sevs = GRAPH.findings.filter((f) => f.ref === n.ref).map((f) => f.severity);
  if (sevs.includes("error")) return "⛔";
  if (sevs.includes("warn")) return "⚠️";
  return "";
}

function render() {
  const svg = $("canvas");
  svg.innerHTML = "";
  if (!GRAPH) return;
  const g = document.createElementNS(SVGNS, "g");
  g.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
  svg.appendChild(g);
  const { w, h } = GRAPH.size;
  const pos = {};
  GRAPH.nodes.forEach((n) => (pos[n.ref] = n));

  for (const e of GRAPH.edges) {
    const a = pos[e.src], b = pos[e.dst];
    const sy = e.error ? h : portY(a.out, e.srcPort, h);
    const sx = e.error ? a.x + w / 2 : a.x + w;
    const x1 = sx, y1 = a.y + (e.error ? h : sy);
    const x2 = b.x, y2 = b.y + portY(b.in, e.dstPort, h);
    const dx = Math.max(40, (x2 - x1) / 2);
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`);
    p.setAttribute("class", "edge" + (e.error ? " error" : "") +
      (SELECTED && (e.src === SELECTED || e.dst === SELECTED) ? " hl" : ""));
    g.appendChild(p);
  }

  const showNotes = $("show-notes").checked;
  for (const n of GRAPH.nodes) {
    const grp = document.createElementNS(SVGNS, "g");
    grp.setAttribute("class", `node kind-${n.kind}` + (n.ref === SELECTED ? " selected" : ""));
    grp.setAttribute("transform", `translate(${n.x},${n.y})`);
    const rect = document.createElementNS(SVGNS, "rect");
    rect.setAttribute("width", w); rect.setAttribute("height", h);
    rect.setAttribute("rx", 8);
    grp.appendChild(rect);
    const t1 = document.createElementNS(SVGNS, "text");
    t1.setAttribute("x", 10); t1.setAttribute("y", 22);
    t1.setAttribute("class", "nref");
    t1.textContent = n.label.length > 26 ? n.label.slice(0, 25) + "…" : n.label;
    grp.appendChild(t1);
    const badge = nodeBadges(n);
    if (badge) {
      const tb = document.createElementNS(SVGNS, "text");
      tb.setAttribute("x", w - 24); tb.setAttribute("y", 20);
      tb.setAttribute("class", "nbadge");
      tb.textContent = badge;
      grp.appendChild(tb);
    }
    const t2 = document.createElementNS(SVGNS, "text");
    t2.setAttribute("x", 10); t2.setAttribute("y", 40);
    t2.setAttribute("class", "nlabel");
    t2.textContent = `${n.ref} · ${n.kind}`;
    grp.appendChild(t2);
    const note = GRAPH.annotations[n.ref];
    if (showNotes && note) {
      const tn = document.createElementNS(SVGNS, "text");
      tn.setAttribute("x", 10); tn.setAttribute("y", 54);
      tn.setAttribute("class", "notecap");
      tn.textContent = note.length > 38 ? note.slice(0, 37) + "…" : note;
      grp.appendChild(tn);
    }
    grp.onclick = (ev) => { ev.stopPropagation(); select(n.ref); };
    g.appendChild(grp);
  }
}

function select(ref) {
  SELECTED = ref;
  const n = GRAPH.nodes.find((x) => x.ref === ref);
  $("side-empty").hidden = true;
  $("node-detail").hidden = false;
  $("node-title").textContent = `${n.ref} — ${n.label}`;
  $("node-note").textContent = GRAPH.annotations[n.ref] || "";
  $("node-block").textContent = n.block;
  renderFindings(GRAPH.findings.filter((f) => f.ref === ref), `Findings on ${ref}`);
  render();
}
function renderFindings(findings, title) {
  const box = $("findings");
  box.innerHTML = "";
  box.appendChild(el("h2", {}, title || "Findings"));
  if (!findings.length) box.appendChild(el("div", { class: "dim" }, "none"));
  for (const f of findings) {
    const d = el("div", { class: "finding " + f.severity });
    d.appendChild(el("div", { class: "fhead" },
      `${f.severity.toUpperCase()} [${f.check}] ${f.ref || "pipeline"}`));
    d.appendChild(el("div", { class: "fmsg" }, f.message));
    if (f.ref) d.onclick = () => select(f.ref);
    box.appendChild(d);
  }
}

async function loadPipeline(f) {
  setMsg($("pipeline-msg"), "loading…");
  try {
    GRAPH = await api("/api/graph?f=" + encodeURIComponent(f));
    SELECTED = null;
    $("node-detail").hidden = true;
    $("side-empty").hidden = false;
    const maxX = Math.max(...GRAPH.nodes.map((n) => n.x), 0) + 260;
    view.k = Math.min(1, ($("canvas-wrap").clientWidth - 40) / maxX);
    view.x = 20; view.y = 20;
    renderFindings(GRAPH.findings);
    render();
    setMsg($("pipeline-msg"),
      `${GRAPH.nodes.length} nodes, ${GRAPH.edges.length} edges, ` +
      `${GRAPH.findings.length} finding(s)`);
  } catch (e) { setMsg($("pipeline-msg"), e.message, true); }
}
$("file-select").onchange = () => loadPipeline($("file-select").value);
$("show-notes").onchange = render;
$("annotate-btn").onclick = async () => {
  setMsg($("pipeline-msg"), "annotating via LLM…");
  try {
    const data = await api("/api/annotate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ f: $("file-select").value }),
    });
    GRAPH.annotations = data.annotations;
    render();
    if (SELECTED) select(SELECTED);
    setMsg($("pipeline-msg"), "annotated " + Object.keys(data.annotations).length + " node(s)");
  } catch (e) { setMsg($("pipeline-msg"), e.message, true); }
};

/* pan / zoom */
(() => {
  const wrap = $("canvas-wrap");
  let drag = null;
  wrap.addEventListener("mousedown", (e) => {
    drag = { x: e.clientX - view.x, y: e.clientY - view.y };
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    view.x = e.clientX - drag.x; view.y = e.clientY - drag.y;
    render();
  });
  window.addEventListener("mouseup", () => (drag = null));
  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const rect = wrap.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    view.x = mx - (mx - view.x) * factor;
    view.y = my - (my - view.y) * factor;
    view.k *= factor;
    render();
  }, { passive: false });
})();

/* ---------- diff view ---------- */
function diffTable(rows) {
  // Side-by-side split: pair each run of deletions with the following adds.
  const table = el("table", { class: "diff" });
  const cell = (tr, cls, num, text, sign) => {
    tr.appendChild(el("td", { class: "num " + cls }, num || ""));
    const td = el("td", { class: "code mono " + cls }, text ?? "");
    if (sign) td.dataset.sign = sign;
    tr.appendChild(td);
  };
  const flush = (dels, adds) => {
    for (let i = 0; i < Math.max(dels.length, adds.length); i++) {
      const tr = el("tr", {});
      const d = dels[i], a = adds[i];
      d ? cell(tr, "cdel", d.an, d.s, "-") : cell(tr, "cempty");
      a ? cell(tr, "cadd", a.bn, a.s, "+") : cell(tr, "cempty");
      table.appendChild(tr);
    }
  };
  let dels = [], adds = [];
  for (const r of rows) {
    if (r.t === "del") { dels.push(r); continue; }
    if (r.t === "add") { adds.push(r); continue; }
    flush(dels, adds); dels = []; adds = [];
    const tr = el("tr", { class: r.t === "gap" ? "gap" : "" });
    if (r.t === "gap") tr.appendChild(el("td", { colspan: 4 }, "· · ·"));
    else { cell(tr, "", r.an, r.s); cell(tr, "", r.bn, r.s); }
    table.appendChild(tr);
  }
  flush(dels, adds);
  return table;
}
function diffFileBox(title, payload) {
  const box = el("div", { class: "difffile" });
  const head = el("div", { class: "dhead" });
  head.appendChild(el("span", {}, title));
  head.appendChild(el("span", { class: "dstat-add" }, `+${payload.stats.add}`));
  head.appendChild(el("span", { class: "dstat-del" }, `−${payload.stats.del}`));
  if (payload.renames && payload.renames.length) {
    head.appendChild(el("span", { class: "renames" },
      "renumbered: " + payload.renames.map((r) => `${r.from}→${r.to}`).join(", ")));
  }
  box.appendChild(head);
  if (payload.new_findings && payload.new_findings.length) {
    const fbox = el("div", { class: "newfindings" });
    fbox.appendChild(el("div", { class: "fhead" },
      `⚠ ${payload.new_findings.length} finding(s) introduced by this change`));
    for (const f of payload.new_findings) {
      const d = el("div", { class: "finding " + f.severity });
      d.appendChild(el("div", { class: "fhead" },
        `${f.severity.toUpperCase()} [${f.check}] ${f.ref || "pipeline"}`));
      d.appendChild(el("div", { class: "fmsg" }, f.message));
      fbox.appendChild(d);
    }
    box.appendChild(fbox);
  }
  if (!payload.rows.length) box.appendChild(el("div", { class: "dhead dim" }, "no changes"));
  else box.appendChild(diffTable(payload.rows));
  return box;
}
/* ---------- PR view ---------- */
$("pr-mode").onchange = () => {
  const local = $("pr-mode").value === "local";
  $("pr-url").hidden = local;
  $("pr-local").hidden = !local;
};
$("pr-url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("pr-btn").click();
});
$("pr-btn").onclick = async () => {
  setMsg($("pr-msg"), "fetching PR via git… (first use of a repo clones a blob-less cache; may take a moment)");
  try {
    let query;
    if ($("pr-mode").value === "url") {
      query = `url=${encodeURIComponent($("pr-url").value.trim())}`;
    } else {
      const repo = $("pr-repo").value.trim(), n = $("pr-num").value.trim();
      query = `repo=${encodeURIComponent(repo)}&n=${encodeURIComponent(n)}`;
    }
    const data = await api(`/api/pr?${query}`);
    const out = $("pr-out");
    out.innerHTML = "";
    setMsg($("pr-msg"),
      `${data.base}…${data.head} — ${data.files.length} .slp file(s) changed`);
    if (!data.files.length) out.appendChild(el("div", { class: "dim" },
      "This PR changes no .slp files."));
    for (const f of data.files) out.appendChild(diffFileBox(f.path, f));
  } catch (e) { setMsg($("pr-msg"), e.message, true); }
};

/* ---------- chat view ---------- */
const CHAT = []; // {role, content}
function bubble(role, content, pending) {
  const b = el("div", { class: `bubble ${role}` + (pending ? " pending" : "") }, content);
  $("chat-log").appendChild(b);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return b;
}
$("chat-file").addEventListener("change", () => {
  CHAT.length = 0;
  $("chat-log").innerHTML = "";
});
$("chat-form").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("chat-input").value.trim();
  if (!text) return;
  $("chat-input").value = "";
  CHAT.push({ role: "user", content: text });
  bubble("user", text);
  const pending = bubble("assistant", "thinking…", true);
  try {
    const data = await api("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ f: $("chat-file").value, messages: CHAT }),
    });
    pending.remove();
    CHAT.push({ role: "assistant", content: data.reply });
    bubble("assistant", data.reply);
  } catch (err) {
    pending.remove();
    bubble("assistant", "⚠ " + err.message);
  }
};
$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("chat-form").requestSubmit();
  }
});

loadFiles().catch((e) => setMsg($("pipeline-msg"), e.message, true));
