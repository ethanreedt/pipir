# ETL-IR worked examples (Phase 1)

Both examples use **real fragments** from `fixtures/real/sub_INT8000_QV_RPT_WS.slp`
(public GitHub repo SashikumarKota/SnaplogicUAT), trimmed for brevity. UUIDs shortened
for display.

---

## Example 1 — Router (typed extractor)

### Before: `.slp` fragment

```json
"snap_map": {
  "6f2c81aa-…": {
    "class_id": "com-snaplogic-snaps-flow-router",
    "class_version": 1,
    "instance_id": "6f2c81aa-…",
    "property_map": {
      "info": { "label": {"value": "Router"} },
      "settings": {
        "firstMatch": {"value": false},
        "persistence": {"value": "No Cache"},
        "routes": {"value": [
          { "expression": {"expression": true, "value": "_fileName.contains(\"xlsx\")"},
            "outputViewName": {"value": "output0"} },
          { "expression": {"expression": true, "value": "!_fileName.contains(\"xlsx\")"},
            "outputViewName": {"value": "output1"} }
        ]}
      },
      "input":  { "input0":  { "label": {"value": "input0"},  "view_type": {"value": "document"} } },
      "output": { "output0": { "label": {"value": "output0"}, "view_type": {"value": "document"} },
                  "output1": { "label": {"value": "output1"}, "view_type": {"value": "document"} } },
      "error":  { "error0":  { "label": {"value": "error0"},  "view_type": {"value": "document"} },
                  "error_behavior": {"value": "fail"} },
      "view_serial": 100
    }
  }
}
```

### After: IR

```
node route.1 route native=flow-router
  label "Router"
  in in0
  out out0
  out out1
  err err0 fail
  first-match off
  when expr "_fileName.contains(\"xlsx\")" -> out0
  when expr "!_fileName.contains(\"xlsx\")" -> out1
  set persistence "No Cache"
```

Notes: `first-match` is always emitted, on or off, since it changes how routes read.
`routes` was consumed by the `when` statements; the one remaining setting
(`persistence`) survives as a `set` line. `view_serial`, `instance_id`,
`class_version` dropped.

---

## Example 2 — Mapper + Email Sender (opaque fallback with account) + Pipeline Execute, with edges

### Before: `.slp` fragment

```json
{
  "property_map": {
    "info": { "label": {"value": "sub_INT8000_QV_RPT_WS"} },
    "settings": {
      "param_table": {"value": [
        { "capture": {"value": true}, "key": {"value": "fileName"},   "value": {"value": null} },
        { "capture": {"value": true}, "key": {"value": "LogIntoDB"},  "value": {"value": null} },
        { "capture": {"value": true}, "key": {"value": "ToTechEmail"},"value": {"value": null} }
      ]},
      "imports": {"value": []},
      "error_pipeline": {"expression": false, "value": null}
    }
  },
  "snap_map": {
    "a01b334c-…": {
      "class_id": "com-snaplogic-snaps-transform-datatransform",
      "property_map": {
        "info": {"label": {"value": "Mapper--Set the variables for logging"}},
        "settings": {
          "nullSafeAccess": {"value": false},
          "passThrough": {"value": false},
          "transformations": {"value": {
            "mappingRoot": {"value": "$"},
            "mappingTable": {"value": [
              { "expression": {"expression": true, "value": "_LogIntoDB"}, "targetPath": {"value": "$LogIntoDB"} },
              { "expression": {"expression": true, "value": "false"},      "targetPath": {"value": "$CreateJIRA"} }
            ]}}}
        },
        "input":  { "input0":  {"label": {"value": "input0"},  "view_type": {"value": "document"}} },
        "output": { "output0": {"label": {"value": "output0"}, "view_type": {"value": "document"}} },
        "error":  { "error0":  {"label": {"value": "error0"},  "view_type": {"value": "document"}},
                    "error_behavior": {"value": "fail"} }
      }
    },
    "11111111-…": {
      "class_id": "com-snaplogic-snaps-email-emailsender",
      "property_map": {
        "info": {"label": {"value": "Send email when logging operation(s) fails"}},
        "account": { "account_ref": { "expression": false, "value": {
          "label":        {"expression": false, "value": "RIM.NET"},
          "ref_class_id": {"value": "com-snaplogic-snaps-email-smtpaccount"},
          "ref_id":       {"expression": false, "value": null} } } },
        "settings": {
          "attachments": {"value": []},
          "batchSize": {"value": 100},
          "body":    {"expression": true,  "value": "$"},
          "emailType": {"value": "HTML text"},
          "retries": {"value": 3},
          "subject": {"expression": true,  "value": "pipe.label + \" Pipeline Failed During Logging Operation\""},
          "to":      {"expression": true,  "value": "_ToTechEmail"}
        },
        "input": { "input101": {"label": {"value": "input0"}, "view_type": {"value": "document"}} },
        "error": { "error0": {"label": {"value": "error0"}, "view_type": {"value": "document"}},
                   "error_behavior": {"value": "fail"} }
      }
    },
    "c44d90ef-…": {
      "class_id": "com-snaplogic-snaps-flow-pipeexec",
      "property_map": {
        "info": {"label": {"value": "Execute DB logging pipeline"}},
        "settings": {
          "pipeline": {"expression": false, "value": "../shared/INT1000_Data_Logging"},
          "params": {"value": []},
          "poolSize": {"expression": false, "value": 1},
          "reuse": {"value": false},
          "snaplex": {"expression": false, "value": null},
          "execLabel": {"expression": true, "value": null},
          "loopDocument": {"expression": true}
        },
        "input":  { "input0":  {"label": {"value": "input0"},  "view_type": {"value": "document"}} },
        "output": { "output0": {"label": {"value": "output0"}, "view_type": {"value": "document"}} },
        "error":  { "error0":  {"label": {"value": "error0"},  "view_type": {"value": "document"}},
                    "error_behavior": {"value": "fail"} }
      }
    }
  },
  "link_map": {
    "link297": { "src_id": "a01b334c-…", "src_view_id": "output0",
                 "dst_id": "c44d90ef-…", "dst_view_id": "input0" },
    "link301": { "src_id": "c44d90ef-…", "src_view_id": "error0",
                 "dst_id": "11111111-…", "dst_view_id": "input101" }
  }
}
```

### After: IR

```
etl-ir 0.1
dialect snaplogic

pipeline "sub_INT8000_QV_RPT_WS"

param fileName
param LogIntoDB
param ToTechEmail

node map.1 map native=transform-datatransform
  label "Mapper--Set the variables for logging"
  in in0
  out out0
  err err0 fail
  map expr "_LogIntoDB" -> "$LogIntoDB"
  map expr "false" -> "$CreateJIRA"

node exec.1 exec native=flow-pipeexec
  label "Execute DB logging pipeline"
  in in0
  out out0
  err err0 fail
  call "../shared/INT1000_Data_Logging"
  set execLabel expr null
  set executable_during_suggest true
  set loopDocument expr null
  set poolSize 1
  set reuse false
  set snaplex null

node op.1 opaque native=email-emailsender
  label "Send email when logging operation(s) fails"
  in in0
  err err0 fail
  account "RIM.NET" type email-smtpaccount
  set attachments []
  set batchSize 100
  set body expr "$"
  set emailType "HTML text"
  set retries 3
  set subject expr "pipe.label + \" Pipeline Failed During Logging Operation\""
  set to expr "_ToTechEmail"

edge map.1:out0 -> exec.1:in0
edge exec.1:err0 -> op.1:in0

; end
```

Notes:

- Reading top to bottom: a mapper sets logging variables, feeds a child-pipeline call,
  and if that call errors, an email goes out. The error branch is an ordinary edge.
- `link297`/`link301` keys are gone; edge order is canonical.
- The Email Sender is an `opaque` fallback: everything preserved, nothing modeled —
  `native=` + `opaque` is the flag that a typed extractor could be added.
- The email snap's serial view key `input101` becomes plain `in0` — original keys are
  serial-counter artifacts and are dropped; user-given port labels (none here) would be
  kept via `label "…"`.
- `loopDocument` shows the `{"expression": true}`-with-no-value edge case → `expr null`.
- A grep for `_ToTechEmail` finds the param declaration and its one use; a diff after
  someone edits a route condition touches exactly one `when` line.
```
