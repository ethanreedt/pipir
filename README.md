# pipir — SnapLogic `.slp` → ETL-IR converter

Converts SnapLogic pipeline exports into **ETL-IR** (`.pipir`): a line-oriented,
assembly-flavored, platform-neutral text format built for human reading, useful PR
diffs, and ad-hoc scripting. The format is defined in [SPEC.md](SPEC.md); worked
before/after examples are in [EXAMPLES.md](EXAMPLES.md).

Python 3, stdlib only.

## Usage

```sh
python -m pipir input.slp                 # IR to stdout
python -m pipir input.slp -o out.pipir    # IR to a file
python -m pipir --from slp input.slp      # explicit input dialect (default: slp)
python -m pipir --coverage input.slp      # typed/classified/opaque snap report
```

`--from` (dest `input_type`) names the input dialect; `slp` is the only one today —
the flag exists so other platforms' exports can slot in later.

`--coverage` groups snaps into three tiers of converter understanding. **typed**: a
dedicated extractor models the snap's behavior as readable statements (`map … -> …`,
`when … -> out0`, `call "…"`) — Mapper, Router, Filter, Join, Pipeline Execute.
**classified**: the snap's role is known (`source`, `sink`, `parse`, `union`, …) but
its settings are emitted as generic `set` lines. **opaque**: unknown class_id — kind
`opaque` flags it, settings still fully preserved. Settings are never dropped in any
tier; the tiers differ only in how much the IR interprets for you.

## Layout

| Path | What |
|---|---|
| `pipir/unwrap.py` | .slp value/expression wrapper unwrapping (SPEC §8) |
| `pipir/parse_slp.py` | .slp JSON → neutral model; accepts both export variants |
| `pipir/kinds.py` | class_id → neutral kind taxonomy (SPEC §7) |
| `pipir/extract.py` | typed extractors: Mapper, Router, Filter, Join, PipeExec |
| `pipir/order.py` | deterministic dataflow ordering + `map.1`-style mangling (SPEC §5) |
| `pipir/emit.py` | canonical text emission (SPEC §2, §9) |
| `pipir/report.py` | `--coverage` implementation |
| `fixtures/real/` | real `.slp` files from public GitHub repos |
| `fixtures/golden/` | committed expected IR, one per real fixture |

## Tests

```sh
python -m unittest discover tests             # golden + determinism + unit
PIPIR_REGEN=1 python -m unittest discover tests   # regenerate golden files
```

Golden tests diff converter output against `fixtures/golden/`. Determinism tests
apply cosmetic mutations to each fixture — shuffled object keys, shuffled
`snap_map`, renumbered `linkNNN` keys, perturbed/removed `render_map`, mutated
save-version metadata, re-serialization — and assert byte-identical IR (SPEC §9).
