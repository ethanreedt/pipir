# ETL-IR — a platform-neutral, human-readable intermediary representation for ETL pipelines

**Version: 0.1 (draft, Phase 1 — awaiting sign-off)**
**Status: proposal. No converter exists yet.**

ETL-IR is a line-oriented, assembly-flavored text format describing one ETL pipeline as a
directed graph of components. It is designed to be:

- **readable** — someone familiar with this spec can read a `.pipir` file top to bottom and
  understand the pipeline, the way one reads assembly: one statement per line, a small
  keyword vocabulary, labels, comments;
- **diffable** — PR diffs show exactly which mapping row / route / edge changed;
- **scriptable** — strict line grammar, greppable (`grep '^\s*when '`, `grep -F '_fileName'`);
- **deterministic** — two exports of the same pipeline produce byte-identical IR;
- **logic-only** — all platform housekeeping metadata (UUIDs, serial counters, canvas
  layout, save-versions, tombstones) is stripped. What survives is what a person typed in
  or wired up.

---

## 1. Scope and guiding decisions

Decisions confirmed with the project owner (2026-07-08):

1. **Text DSL, not JSON.** The IR is a text format optimized for human reading and diffs.
   (A JSON emitter can be added later as a converter flag if a script ever needs it; the
   text form is canonical.)
2. **All SnapLogic metadata is removed.** No instance UUIDs, no `class_version` counters,
   no `snap_history`, no `render_map`, no snode/path ids. Components get compiler-style
   **mangled names** (`map.1`, `route.1`, …) assigned deterministically (§5).
3. **Expressions are preserved verbatim, and only verbatim.** No token extraction, no AST.
   Scripts that need to find references do a string search. (This descopes the original
   C.2 "extracted refs" requirement — owner's call.)
4. Scope is one pipeline per file. Cross-pipeline references stay unresolved (§7.8).

---

## 2. File conventions

- Extension: **`.pipir`** ("pipeline IR"). Encoding UTF-8, `\n` line endings, exactly one
  trailing newline.
- Indentation: exactly 2 spaces per level. No tabs.
- Comments: `;` to end of line. The converter emits comments only where this spec says so
  (they are part of the canonical bytes and therefore deterministic).
- One pipeline per file. Statement order is fully specified (§6), so canonical output is
  unique.

### 2.1 Tokens and values

- **Bareword**: `[A-Za-z0-9_.\-]+` — used for keywords, node ids, port names, kinds.
- **String**: JSON string syntax, double-quoted, JSON escapes. Any value that is not a
  bareword-safe identifier is emitted as a JSON string.
- **Scalar values** (in `set` / `arg` / `param` statements): JSON literals — `123`,
  `true`, `false`, `null`, `"a string"`.
- **Expression values**: prefixed with the keyword `expr`, then a JSON string holding the
  SnapLogic expression **verbatim**: `expr "_fileName.contains(\"xlsx\")"`.
  `expr null` represents the observed wrapper edge case `{"expression": true}` with a
  missing or null `value`.
- **Multi-line strings** (SQL text, email bodies): block form. The line ends with `|`
  (or `expr |` when the value is a multi-line expression), and the content follows,
  each line prefixed with the statement's indent + 2 spaces. Content lines are
  verbatim — including trailing whitespace; an empty content line is emitted as its
  indent prefix only, so it still belongs to the block. The block ends at the first
  line whose indentation drops below the content indent. Block form is used only in
  `set` statements; expressions embedded in typed statements (`map`, `when`, …) stay
  one-line JSON strings (multi-line ones are rare there).

  ```
  set sqlStatement |
    SELECT *
    FROM orders
    WHERE id = ?
  set body expr |
    "<html><body>" + $entity.name +
    "</body></html>"
  ```

### 2.2 Nested settings (`set` paths)

Most snap settings are simple scalars and become one `set name value` line each. But
some settings are **nested structures** — arrays of objects, objects inside objects.
For example, a REST Get snap's query parameters are stored in the `.slp` as an array
of `{queryParam, queryParamValue}` objects:

```json
"queryParams": { "value": [
  { "queryParam":      {"value": "q"},
    "queryParamValue": {"expression": true, "value": "$textBody"} },
  { "queryParam":      {"value": "appid"},
    "queryParamValue": {"expression": false, "value": "b6907d28…"} }
]}
```

Rather than embedding a JSON blob on one line (unreadable, undiffable), the IR flattens
each leaf to its own `set` line, using dotted paths and `[n]` array indices:

```
set queryParams[0].queryParam "q"
set queryParams[0].queryParamValue expr "$textBody"
set queryParams[1].queryParam "appid"
set queryParams[1].queryParamValue "b6907d28…"
```

Editing one query parameter now changes exactly one line, and
`grep 'queryParam '` finds them all. (This is a real example from the Weather_Report
fixture. Router `routes` and Mapper `mappingTable` are also nested, but those are
consumed by their typed statements — §7.2, §7.1 — so `set` flattening applies to
whatever nested settings *remain*, and to everything on `opaque` nodes.)

Path segments that are not bareword-safe are quoted: `set headers["Content-Type"] "text/xml"`.
Empty array → `set attachments []`; empty object → `set foo {}` (kept so nothing is
silently dropped).

---

## 3. Document structure

Sections appear in this fixed order (empty sections are omitted):

```
etl-ir 0.1
dialect snaplogic

pipeline "sub_INT8000_QV_RPT_WS"

; parameters
param fileName
param QlikviewServer

; pipeline-level
import "shared/utils.expr"
on-error pipeline "../shared/ErrorHandler"
on-error behavior none

; nodes (dataflow order)
node <id> <kind> native=<type>
  ...

; edges
edge map.1:out0 -> route.1:in0
...

; pipeline i/o (open views exposed as sub-pipeline input/output)
pipeline-in  <node>:<port> label "..."
pipeline-out <node>:<port> label "..."
```

Header lines:

| Statement | Meaning |
|---|---|
| `etl-ir 0.1` | IR version (the only mandatory metadata) |
| `dialect snaplogic` | source platform; scopes the meaning of `native=` types and expression syntax |
| `pipeline "<name>"` | pipeline label from `property_map.info.label`. Older exports store no label at all (`{}`); the converter then falls back to the input file's stem and flags it: `pipeline "sub_INT8000_QV_RPT_WS" ; name from filename (export carries no label)` |
| `param <name> [<default>]` | pipeline parameter; default shown only when non-null (JSON scalar or `expr "…"`). The `capture` flag is emitted as `param <name> nocapture` only when false (true is the observed default). |
| `import "<path>"` | expression-library import |
| `on-error pipeline "<path>"` | pipeline-level error handler, when set; its `error_param_table` rows become indented `arg` lines |
| `on-error behavior <word>` | pipeline-level `error.error_behavior`, when present |

Handler vs. behavior — these are two different things, and both exist at pipeline
level. The **handler** (`property_map.settings.error_pipeline`) names another pipeline
to run on failure. The **behavior** is a `fail`/`continue`/`discard`-style flag. You're
right that behavior is normally snap-level (each snap's `error` view map carries an
`error_behavior`, and the IR puts it on the snap's `err` port, §4.1) — but the real
files also show one at *pipeline* level: the Weather_Report fixture has
`property_map.error = {"error_behavior": {"value": "none"}}` at the pipeline root.
The `on-error behavior` header line exists only for that pipeline-level flag and is
omitted when absent (it never appears in the older-format fixtures).

Pipeline-level `info.notes`, `info.purpose`, `info.author`, and `pipeline_doc_uri` are
all **dropped** (prose/authorship metadata — resolved with owner). What *is* kept is
the snap-level Info tab: each snap's Notes field (`info.notes`), where per-snap
comments are written at length, is emitted as `; note:` comment lines right after the
node's `label`, multi-line text as one comment line per line:

```
node map.1 map native=transform-datatransform
  label "Mapper--Set the variables for logging"
  ; note: Sets logging vars; see INT1000 runbook.
  in in0
  ...
```

---

## 4. Nodes

```
node map.1 map native=transform-datatransform
  label "Mapper--Set the variables for logging"
  in  in0
  out out0
  err err0 continue
  root "$"
  nullsafe on
  map expr "_LogIntoDB" -> "$LogIntoDB"
  map expr "false"      -> "$CreateJIRA"
```

Node header: `node <id> <kind> native=<short-type>` where `<short-type>` is the snap
`class_id` with the constant `com-snaplogic-snaps-` prefix removed (the `dialect` line
makes it recoverable). `class_version` is dropped (resolved with owner: metadata, and
this is a post-hoc tool).

Body statements, in fixed order:

1. `label "<human label>"` — always present; display-only, never identity.
2. **Port declarations** (§4.1). 
3. `account …` (§7.6), when the snap has one.
4. **Kind-specific statements** (§7). For snap types the converter understands, the
   interesting part of the config is promoted out of the generic `set` dump into
   dedicated, readable statements — the way assembly gives common operations their own
   mnemonic instead of raw bytes. Concretely: a Mapper's `mappingTable` (a nested
   settings array, §2.2) becomes one `map <expr> -> <target>` line per row; a Router's
   `routes` array becomes `when <predicate> -> <port>` lines; a Pipeline Execute's
   child reference becomes `call "<path>"`. Same information as the raw settings —
   just rendered in a form you can read and diff. Only the snap types listed in §7 get
   this treatment; everything else keeps its settings as plain `set` lines.
5. `set …` lines — every remaining native setting, unwrapped and flattened (§2.2),
   sorted by path. For typed extractors these are the settings *not* consumed by the
   kind-specific statements; for opaque nodes it is all of them. Nothing is dropped.

### 4.1 Ports

Real files show that a snap's view **map keys** are what `link_map` references, and they
are serial-numbered artifacts (`input101`, `output102`), while the view **label** is the
human name and may carry real meaning (a Union's inputs labeled `Fail_Parse`, `Success`).

The IR therefore renames ports to canonical slots and keeps meaningful labels:

- Inputs → `in0, in1, …`; outputs → `out0, out1, …`; error → `err0`. Slot indices are
  assigned by sorting original view keys by their numeric suffix (`input0` < `input1` <
  `input101`), which reflects creation order.
- Declaration: `in in0`, `out out1`, `err err0 <behavior>` where `<behavior>` is the
  snap's `error.error_behavior` — this *is* logic. The stored words map to the UI's
  "When errors occur" options non-obviously: `fail` = Stop Pipeline Execution,
  `discard` = Discard Error Data and Continue, `continue` = **Route Error Data to
  Error View** (not "discard and continue"). The IR keeps the stored words verbatim.
  A `none` (seen pipeline-level) is an unconfigured-views serialization artifact and
  is suppressed.
- When the original label differs from a bare `inputN/outputN` pattern, it is kept:
  `in in2 label "Fail_Parse"`.
- `view_type` is emitted only when `binary`: `in in0 binary` (document is the default).
- Typed extractors **rewrite** internal view references to slot names (Router route
  targets, Join `rightInputView`). Opaque nodes keep original view-key strings inside
  their `set` lines verbatim; the original keys are serial-counter artifacts and are
  otherwise dropped (resolved with owner: user-given labels remain, key naming doesn't
  matter).

Unconnected declared views are still declared (they are part of the snap's shape).

---

## 5. Node naming (mangling) and ordering

Node ids are `<mnemonic>.<N>`: the kind's mnemonic (§7 table) plus a 1-based ordinal
assigned **per mnemonic** in global emission order. E.g. twelve Mappers become
`map.1 … map.12`; three "Mapper2"-labeled snaps get distinct ids by position.

**Emission order** (also edge/section order) is dataflow order:

1. Compute topological order over the data edges (SnapLogic graphs are DAGs).
2. Tie-breaks, in order: topological depth (longest path from a source), then `kind`,
   then `native` type, then `label`, then the canonicalized settings content, then a
   recursive neighbor signature.
3. If two nodes are still indistinguishable, they are interchangeable by construction —
   any fixed order yields the same bytes. (Internally the converter uses the stable
   `instance_id` as a final hidden tie-break; it never appears in the output, so
   byte-determinism holds either way.)

Because ordering depends only on graph content — never on JSON key order, `linkNNN`
numbering, or UUIDs — re-exports of the same pipeline mangle identically, and even a
pipeline rebuilt from scratch with the same logic produces the same IR.

**Edges** are emitted as `edge <src>:<port> -> <dst>:<port>`, sorted by (src node
emission index, src port slot, dst node emission index, dst port slot). Volatile
`linkNNN` keys are dropped. Error-branch wiring looks like any other edge:
`edge file.1:err0 -> union.2:in1`.

---

## 6. What is dropped (exhaustive)

| Dropped | Why |
|---|---|
| `render_map`, per-snap `view_serial` | canvas layout / serial counters; change on save |
| top-level `class_id` | constant |
| top-level `class_version`, `class_fqid` | schema-version metadata |
| new-format top-level: `instance_id`, `instance_version`, `snap_history`, `link_serial`, `path_id`, `path_snode`, `snode_id` | save-counters, tombstones, project-location metadata |
| per-snap `instance_id`, `instance_fqid`, `instance_version`, `class_build_tag`, `class_version`, `class_fqid` (the fqid's class part survives as `native=`) | platform identity/build metadata; IR uses mangled names |
| `link_map` keys | volatile; edges are canonical tuples |
| pipeline `info.notes`, `info.purpose`, `info.author`, `pipeline_doc_uri` | prose/authorship metadata (snap-level Info notes are kept, §3) |
| snap `info` fields other than `label` and `notes` | ditto |
| account `ref_id` | asset UUID; name + type identify the account to a human |

Everything else — every settings leaf, every expression, every port, every edge — is
preserved.

---

## 7. Kind taxonomy and typed extractors

Neutral `kind` vocabulary, mnemonic, and the SnapLogic mapping for the initial coverage
set:

| kind | mnemonic | SnapLogic `class_id` (short) | notes |
|---|---|---|---|
| `map` | `map` | `transform-datatransform` | field mapping |
| `route` | `route` | `flow-router` (also seen as `transform-router` in older docs) | conditional fan-out |
| `filter` | `filter` | `flow-filter` | keep/drop rows |
| `join` | `join` | `transform-multijoin`, `transform-join` | multi-input join |
| `union` | `union` | `flow-union` | merge streams |
| `copy` | `copy` | `flow-copy` | duplicate stream |
| `sort` | `sort` | `transform-sort` | |
| `aggregate` | `agg` | `transform-aggregate`, `transform-groupbyfields` | |
| `parse` | `parse` | `transform-csvparser`, `-jsonparser`, `-xmlparser`, `-excelparser`, `-binarytodocument` | binary → documents |
| `format` | `format` | `transform-csvformatter`, `-jsonformatter`, `-xmlformatter`, `-documenttobinary` | documents → binary |
| `source` | `read` | `binary-simpleread` (File Reader), `binary-multifilereader`, DB select/read snaps, `email-emailreader`, JMS consumer | reads from an external system |
| `sink` | `write` | `binary-simplewrite` (File Writer), DB insert/update snaps, `email-emailsender`, JMS producer, `blackberry-postfile` | writes/sends to an external system |
| `call` | `call` | `rest-get`, `rest-post`, `rest-put`, `rest-delete`, SOAP execute, DB Execute snaps (`*-execute`: generic JDBC/MySQL/Oracle/SQL Server "Execute") | per-document request/response to an external system |
| `exec` | `exec` | `flow-pipeexec` | run child pipeline (unresolved) |
| `script` | `script` | `script-script`, expression-eval snaps | embedded code |
| `effect` | `effect` | `binary-delete` (File Delete), file move/copy snaps | external side effect, documents pass through |
| `opaque` | `op` | everything else | generic fallback (§7.9) |

Snaps that resist clean classification get their best-fit kind and keep full settings;
genuinely unclassifiable ones fall back to `opaque`. The `native=` type always preserves
the exact source of truth. The classifier maps by `class_id`; unknown DB/REST families
default to `opaque` rather than guessing `source`/`sink`.

The **DB "Execute" snap** is the poster child for resisting classification: it runs an
arbitrary SQL statement, which may be a SELECT (source-like), an UPDATE/INSERT
(sink-like), or DDL (pure side effect) — and the class_id alone can't tell which. It is
classified as `call` (statement out, result set back), with the SQL statement itself
preserved verbatim in its settings — typically a multi-line `set sqlStatement |` block
(§2.1) — so the reader sees exactly what runs. Anyone scripting over the IR who needs
read/write discrimination must inspect the SQL text, not the kind.

Kind-specific statement forms:

### 7.1 `map` (Mapper)

```
root "$"                ; mappingRoot, omitted when "$"
passthrough on          ; omitted when off (default)
nullsafe on             ; omitted when off (default — untouched snaps store false)
map expr "_fileName" -> "$Path"
map expr "$LogIntoDB" -> "$Database.LogIntoDB"
map expr "$junk" ->                       ; target absent = delete field at path
```

Semantics per the official docs: `passthrough` copies unmapped input fields to the
output; `nullsafe` makes missing source paths evaluate to null instead of erroring; a
row with an empty target path treats the expression as a path and *deletes* it.

`map` rows keep table order (order is semantic). Left side is `expr "…"` or a JSON
literal when the wrapper says `expression: false`; right side is the `targetPath`
verbatim as a string.

### 7.2 `route` (Router)

```
first-match off         ; always emitted — the on/off semantics matter
when expr "_fileName.contains(\"xlsx\")" -> out0
when expr "!_fileName.contains(\"xlsx\")" -> out1
```

`first-match` is always emitted (both `on` and `off`), since whether a document can
take multiple branches is central to reading a Router: `on` = IF/ELSE-IF chain (first
true route wins), `off` = document copied to *every* matching route. Routes keep table
order; output view references rewritten to slot names. Documented edge case: a Router
with an *empty* routes table round-robins documents across its outputs — the converter
emits a `; no routes: documents round-robin across outputs` comment there.

### 7.3 `filter`

```
where expr "$status == \"OK\""
nullsafe on             ; omitted when off (default), as with Mapper
```

### 7.4 `join`

```
join inner
on expr "$join1" == in1 expr "$join2"
```

`join <type>` lowercased and hyphenated. Documented legal types: `inner`,
`left-outer`, `outer`, `merge` — there is no right-outer (swap inputs instead), and
`merge` is a keyless positional zip, so a merge join may legitimately have no `on`
lines. One `on` line per `joinPaths` row: left path, the right input slot, right path;
the modern multijoin accepts more than two inputs (one row per extra input view).
Remaining knobs (`sortedStreams` — pre-sorted streaming merge vs. `Unsorted` internal
buffering; `nullGreater` — where nulls sort in key comparison; `noMatchData` — route
unmatched documents to the error view; `nullSafeAccess`) stay as `set` lines.

### 7.5 `union`, `copy`

No kind-specific statements — the ports and edges say everything.

### 7.6 Accounts (any node)

```
account "RIM.NET" type email-smtpaccount      ; by-reference form
account expr "_QlikviewServer"                ; expression-driven form
```

Background: when a snap needs credentials (SMTP, DB, SFTP…), the `.slp` does not store
the credentials themselves — it stores a *pointer* to an account asset saved elsewhere
in SnapLogic. That pointer has three parts: a human-readable name (`label`, e.g.
`"RIM.NET"`), the account type (`ref_class_id`, e.g. `email-smtpaccount`), and an
internal asset UUID (`ref_id`). The IR keeps the name and the type — that is what a
human needs to know which account is in play — and drops the UUID like all other
platform ids (§6). A snap can also pick its account *dynamically* via an expression
(usually a pipeline parameter); that is the `account expr "…"` form above.

Two quirks observed in the real files: the three pointer fields are themselves
value-wrapped (§8) and must be unwrapped recursively, and `ref_id` is often null even
in the by-reference form. When the whole ref is `{}` (snap needs no account), no
`account` line is emitted.

### 7.7 `parse` / `format` / `source` / `sink` / `call` / `effect` / `script`

No dedicated statements in v0.1 — their behaviour lives in their settings, which are
fully preserved as `set` lines (URLs, paths, SQL, headers, verbatim — internal tooling,
no redaction). Typed statement forms (e.g. `uri` for REST, `path` for file snaps) can be
promoted in a v0.2 once we see which reads matter most.

### 7.8 `exec` (Pipeline Execute)

```
node exec.1 exec native=flow-pipeexec
  label "Execute DB logging pipeline"
  ...
  call "../shared/INT1000_Data_Logging"     ; unresolved child reference
  arg batchId expr "$batch"                 ; one per passed param, table order
  set poolSize 1
  set reuse false
```

The child path and passed params are emitted as an unresolved reference; a future
project-level pass can stitch pipelines by matching `call` paths — no re-parsing
needed. (`loopDocument`, seen in real exports, is not a documented Pipeline Execute
setting — looping is a separate PipeLoop snap — so it stays an ordinary `set` line.)

### 7.9 `opaque` (generic fallback — preserve and flag)

```
node op.1 opaque native=blackberry-postfile
  label "Blackberry File Upload"
  in in0
  err err0 fail
  account "QV_WatchDox" type blackberry-blackberryaccount
  set folderId expr "_WorkspaceFolder"
  set overwrite true
  ...every settings leaf...
```

The `opaque` kind *is* the flag ("typed extractor not implemented"); settings are fully
unwrapped and preserved, so nothing is silently dropped. Phase 3's coverage report lists
which `class_id`s land here.

---

## 8. The wrapper convention (unwrapping rules)

In a `.slp`, almost no setting is stored as a plain value. Where you'd expect
`"batchSize": 100`, the file has `"batchSize": {"value": 100}`. The extra object is a
**wrapper**, and its job is to answer one question per field: *is this a literal, or
is it a SnapLogic expression to evaluate at runtime?* That's what the optional
`"expression"` flag means:

```json
"emailType": {"value": "HTML text"}                          // literal string
"to":        {"expression": true,  "value": "_ToTechEmail"}  // expression: evaluate it
"from":      {"expression": false, "value": null}            // literal (flag present but false)
```

Note the middle one: `"_ToTechEmail"` is *code* (a parameter reference), not the text
"_ToTechEmail". Without the flag you could not tell those apart. The IR strips the
wrappers — they are pure plumbing — but preserves the one bit of information they
carry, via the `expr` keyword: `set emailType "HTML text"` vs. `set to expr
"_ToTechEmail"`.

The exact unwrapping rules, for every leaf `{…}` in a snap's `property_map`:

| Shape found in real files | IR rendering |
|---|---|
| `{"value": X}` | JSON literal `X` |
| `{"expression": false, "value": X}` | JSON literal `X` |
| `{"expression": true, "value": "E"}` | `expr "E"` (verbatim) |
| `{"expression": true}` or `{"expression": true, "value": null}` | `expr null` |

Unwrapping is recursive (wrappers nest: `transformations.value.mappingTable.value[…]`,
and account-ref inner fields carry their own `expression` flags). A leaf that is not
wrapper-shaped is preserved as-is.

---

## 9. Determinism guarantees (C.6)

Byte-identical IR is invariant to: JSON key order; `snap_map`/`link_map` iteration
order; `linkNNN` renumbering; presence/mutation of `render_map`; `snap_history` /
`instance_version` churn; and cosmetic re-serialization of the `.slp`. Achieved by:

- content/topology-derived node ordering and mangling (§5) — no reliance on input order;
- canonical edge tuples, sorted (§5);
- canonical port slots (§4.1);
- `set` lines sorted by dotted path within a node;
- fixed 2-space indentation, `\n`, single trailing newline, JSON-escape emission with
  `ensure_ascii` off and no float reformatting (numbers re-emitted via `repr` of the
  parsed JSON number — Python `json` round-trips ints/floats deterministically).

Phase 3 tests mutate a fixture in each cosmetic way and assert identical bytes.

---

## 10. Part A errata — where the real files disagree

Verified against 4 real `.slp` files (SnaplogicUAT `sub_INT8000_QV_RPT_WS.slp`,
SnapLogicDemo `Weather_Report_2018_06_26.slp`, SnapTest JMS reader/writer):

1. **A newer top-level export variant exists** (Weather file): no top-level
   `class_id`/`class_version`; instead `class_fqid` (`com-snaplogic-pipeline_8`),
   `instance_id`, `instance_version` (bumps per save), `snap_history` (includes
   *deleted* snaps with timestamps), `link_serial`, `path_id`, `path_snode`,
   `snode_id`; per-snap extras `class_build_tag`, `class_fqid`, `instance_fqid`,
   `instance_version`. The converter must accept both variants; all the extras are
   metadata and are dropped.
2. **Router's real `class_id` is `com-snaplogic-snaps-flow-router`**, not
   `…transform-router` (the classifier maps both).
3. **`link_map` view ids reference the view-map *keys*, not labels**, and keys are not
   always `input0`-style — serial-numbered keys like `input101`, `output102` appear,
   while the *label* holds `input0` or a custom human name (`Fail_Parse`, `Success`).
   Part A's "views are named output0/input0/error0" describes labels, not keys. Hence
   the port canonicalization in §4.1.
4. **The wrapper can lack `value` entirely** when `expression: true` (observed:
   pipeexec `loopDocument`). Account-ref inner fields are themselves wrapped, and
   `ref_id` may be null even in by-reference form.
5. **`error_behavior` lives inside the `error` view map** alongside `error0`, at both
   snap and pipeline level (`fail` / `continue` / `discard` / `none` observed).
6. **Pipelines can expose snap views as pipeline-level input/output** —
   `property_map.output` keyed `<instance_id>_output102` with a label. Represented as
   `pipeline-in` / `pipeline-out` lines (§3).
7. A snap's `property_map` may lack `output` (terminal snaps) or `account` entirely;
   `class_fqid` is null throughout the older-format files.

---

## 11. Resolution log

Resolved with owner (2026-07-08): text DSL over JSON; strip all metadata; mangled ids
instead of UUIDs; verbatim-only expressions (no ref extraction); preserve-and-flag
fallback (per original C.7, confirmed as `opaque`).

Resolved in review (2026-07-08):

1. **Port slot renaming** (§4.1): rename serial view keys to canonical slots
   (`input101` → `in0`); user-given port labels are preserved via `label "…"`; the
   original keys carry no meaning and are dropped entirely (no tracking comment).
2. **`native=` without version** (§4): `class_version` dropped — this is a post-hoc
   tool, the version doesn't matter.
3. **Notes** (§3): pipeline-level `notes`/`purpose` are dropped; snap-level Info-tab
   Notes (`info.notes`) are kept as `; note:` comment lines — that's where per-snap
   comments are written at length.
4. **File extension**: **`.pipir`** (pipeline IR — owner's suggestion; distinctive and
   unambiguous where `.ir` is generic).
5. **Router `first-match`** (§7.2): always emitted, on or off, for clarity.
6. **DB Execute snaps** (§7): classified as `call`, SQL preserved verbatim.
