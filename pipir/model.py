"""Neutral in-memory model of one pipeline (the thing the emitter serializes)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Port:
    slot: str                 # canonical name: in0 / out1 / err0
    key: str                  # original .slp view-map key (never emitted)
    label: Optional[str]      # kept only when it carries meaning (SPEC §4.1)
    binary: bool = False
    behavior: Optional[str] = None  # error ports only: fail/continue/discard


@dataclass
class Account:
    # By-reference form: name + type. Expression-driven form: expr only.
    name: Any = None          # str, or Expr in odd cases
    type: Optional[str] = None
    expr: Any = None          # Expr when the account is expression-driven


@dataclass
class Node:
    instance_id: str          # stable across re-exports; internal tie-break only
    native: str               # class_id minus the com-snaplogic-snaps- prefix
    kind: str
    mnemonic: str
    label: str
    notes: Optional[str] = None
    inputs: List[Port] = field(default_factory=list)
    outputs: List[Port] = field(default_factory=list)
    errors: List[Port] = field(default_factory=list)
    account: Optional[Account] = None
    statements: List[str] = field(default_factory=list)  # pre-rendered, unindented
    settings: Dict[str, Any] = field(default_factory=dict)  # unwrapped remainder
    ref: str = ""             # mangled id, assigned after ordering (map.1, route.1)
    op: Dict[str, Any] = field(default_factory=dict)  # structured extractor data (for lint)
    # view key -> slot, for rewriting settings references and resolving links
    slot_by_key: Dict[str, str] = field(default_factory=dict)
    slot_by_label: Dict[str, str] = field(default_factory=dict)


@dataclass
class Edge:
    src_id: str               # instance ids until nodes get refs
    src_view: str
    dst_id: str
    dst_view: str


@dataclass
class Param:
    name: str
    default: Any = None       # unwrapped value or Expr; None -> omitted
    capture: bool = True


@dataclass
class Pipeline:
    name: str
    name_from_filename: bool = False
    params: List[Param] = field(default_factory=list)
    imports: List[Any] = field(default_factory=list)
    error_pipeline: Any = None            # str path or Expr, when set
    error_args: List[Tuple[Any, Any]] = field(default_factory=list)
    error_behavior: Optional[str] = None  # pipeline-level, when present
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    # open views exposed as sub-pipeline i/o: (direction, instance_id, view_key, label)
    open_views: List[Tuple[str, str, str, Optional[str]]] = field(default_factory=list)
