# Ontology Compliance Plan

Making the SVO verification pipeline validate the enterprise ontology in
`Ontology n metamodel/` against both its meta-model and the source process
documents in `Documents/`.

Status: **implemented** (2026-08-26). Phases 0-5 and 7 are built and tested;
Phase 6 (traversal simulator) remains deferred. Usage:
`docs/ONTOLOGY_COMPLIANCE.md`. See section 10 for what changed during
implementation.

---

## 1. What we were given

### `Ontology n metamodel/Final_Ontology_meta_model.json` (v2.1)
The abstract blueprint. Defines:
- **7 meta-classes** — `Ontology_Root_Class`, `Actor_Class`, `Activity_Class`,
  `Decision_Class`, `Outcome_Class`, `Information_Class`, `Systems_Class` —
  each with mandatory attributes (enumerated `type` values, SIPOC fields on
  Activity) and mandatory `agent_rules`.
- **`Agent_Rules_Schema`** — `precondition{conditions[], on_fail∈{skip,block}}`,
  `delegation{role}`, `execution[]`, `postcondition[]`.
- **22 edge types** with a strict `valid_from`/`valid_to` grammar.
- **8 systemic rules** — ONT-000..ONT-006 and ONT-013.

### `Ontology n metamodel/Ontology_V4_description.json` (v2.2)
The concrete instance. 74 classes, 85 relationships, 13 systemic rules
(ONT-000..ONT-012).

| meta_class | count |
|---|---|
| Activity_Class | 40 |
| Information_Class | 21 |
| Systems_Class | 6 |
| Decision_Class | 6 |
| Ontology_Root_Class | 1 |
| **Actor_Class** | **0** |
| **Outcome_Class** | **0** |

Content domain: IT Event Management / Incident Management, rooted at
`Enterprise` → `Operations` / `Detect to Correct` / `Configuration Data`.

### `Documents/`
| File | Pages | Role |
|---|---|---|
| `wb_IT - Event Management Process v1.3.pdf` | 10 | Source of truth for the Event Management subtree |
| `wb_incident_management.pdf` | 14 | Source of truth for the Incident subtree |
| `IT4IT Standards c221e.pdf` | 294 | Reference standard behind `Detect to Correct`, `Operations` |

All three extract clean text with `pdfplumber`; the two `wb_*` docs also carry
extractable tables (RACI, KPI, CSF).

---

## 2. What the pipeline does today, and why it doesn't fit

The engine (`src/engine.py`) validates **flat SVO triples** against **one raw
text string**:

```
OntologyAssertion(assertion_id, subject, relation, object, polarity, rule_type)
    → validate_triples_batch(document_id, raw_text, triples)
    → route → lexical/semantic/graph retrieve → fuse → adjudicate → verdict
```

Five structural gaps between that and the ask:

| # | Gap | Where |
|---|---|---|
| G1 | No PDF ingestion at all — `ingest_document` takes `raw_text: str` | `src/ingestion/pipeline.py:193` |
| G2 | `OntologyAssertion` is a flat triple; the ontology's unit of truth is a typed node with `meta_class`, `attributes`, `agent_rules`, `next_pointer` | `src/models.py` |
| G3 | `OntologyViolationValidator` does substring matching on triples — nothing checks meta-class schemas, edge grammar, or ONT-* rules | `src/validation/ontology.py` |
| G4 | `validate_triples_batch` is single-document; the ontology spans three PDFs | `src/engine.py:682` |
| G5 | No API/CLI/UI surface for an ontology-level report | `api/routes/`, `frontend/src/pages/` |

G4 is the mildest: `adjudicate_triple(document_id=None)` already searches
corpus-wide, and every retriever treats `document_id=None` as "no scope filter"
(`src/retrieval/lexical.py:65`). Only the *batch* entry point hard-couples one
document to one ingest.

---

## 3. Two validation planes

The word "validation" means two different things here, and they need separate
machinery:

**Plane A — Structural conformance.** Does `Ontology_V4` conform to
`Final_Ontology_meta_model`? Pure graph/schema checking. Deterministic, fast,
no documents, no ML. This is entirely new code.

**Plane B — Evidential grounding.** Is each claim the ontology makes actually
supported by the source PDFs? This is what the existing retrieval + adjudication
engine already does — it needs a PDF loader in front and an ontology→assertion
projection layer.

A node can pass A and fail B (well-formed but invented) or pass B and fail A
(faithful to the docs but wired up illegally). The report must show both axes
independently.

---

## 4. Findings from a dry run

I ran the checks in section 5 as a throwaway script against the shipped files.
These are real, present-day defects — they become the acceptance fixture for
Phase 1.

**Clean:** 0 dangling edge endpoints, 0 unknown edge types, 0 nodes missing
`agent_rules`, all 74 nodes reachable from `Enterprise`, all 40 Activities carry
the 5 SIPOC keys, all 5 Facts have an incoming `classifies` edge (ONT-011 ✅).

**Defects:**

1. **6 edges violate the meta-model grammar.**
   - `Log Monitor --executes_via--> Cloud Logging` (target is `External System`)
   - `Service Monitor --executes_via--> Cloud Watch` (target is `External System`)
   - `Runbook Activity --executes_via--> Runbook` (target is `Abstracted Enterprise Entity`)
     — the grammar allows `executes_via` only into `Data Service`, which is also
     what ONT-005 (Systems Abstraction Enforcement) demands.
   - `Operations --decomposes_into--> Business Service` — both are
     `Domain Activity`; the grammar restricts `decomposes_into` to
     `Process Activity → Process Activity`.
   - `Configuration Data --connects_to_info--> Configuration` — source is
     `Information_Class`, grammar requires `Activity_Class`.
   - `Handle Duplicate Event --leads_to--> Skip` — `leads_to` must target
     `Outcome_Class`; `Skip` is a `Sub_Process Activity`.
2. **45 of 74 nodes have `agent_rules.precondition.on_fail: null`.** The
   meta-model enumerates `["skip", "block"]`. Violates ONT-013.
3. **5 execution actions are undocumented in the meta-model:**
   `fill_missing_value` (13), `extract_and_append` (12), `traverse_dynamic` (4),
   `conditional_set` (2), `append_payload` (1). The blueprint enumerates only
   `traverse_dfs`, `invoke_tool`, `query_graph`, `set_payload`.
4. **Zero `Outcome_Class` and zero `Actor_Class` instances.** This makes ONT-006
   (every Outcome measurable via `measured_by`) vacuous and ONT-010 (terminal
   state reachability) unsatisfiable — **39 of 40 Activity nodes have no
   outgoing `triggers`/`leads_to`/`on_success`/`on_failure` edge**, so almost
   every horizontal workflow dead-ends rather than terminating at an Outcome.
   Likewise `performs` (Actor → Activity) is never exercised.
5. **Decision node `reason ?` has no incoming `performs_check`** — orphaned
   w.r.t. ONT-003 (a Decision Node must exist as a component of an Activity).
6. **`Escalation.next_pointer` lists `API Endpoint`, but no such relationship
   exists** in the `relationships` array. `next_pointer` and `relationships` are
   two representations of the same graph and disagree in exactly one place.
7. **Rule-set version skew.** The meta-model (v2.1) carries ONT-000..006 +
   ONT-013. The ontology (v2.2) carries ONT-000..012. ONT-007..012 have no
   blueprint counterpart; ONT-013 is absent from the instance. There is no
   single authoritative rule list.

---

## 5. Rule coverage: what is statically checkable

Not every ONT-* rule is a static graph property. Several describe **agent
runtime behaviour** and can only be approximated statically or checked by
simulating a traversal.

| Rule | Description | Check type | Approach |
|---|---|---|---|
| ONT-000 | Root Singularity | static | exactly one `Enterprise Root`; all nodes reachable from it |
| ONT-001 | SIPOC Completeness | static | Activity has non-empty supplier/input/output/customer (treating `["null"]` as empty) before any `next_pointer` |
| ONT-002 | Constraint Inheritance | static (weak) | child constraint set ⊇ parent's; needs a constraint model first |
| ONT-003 | Decision Placement | static | every `Decision Node` has ≥1 incoming `performs_check`; no Decision has non-evaluative execution actions |
| ONT-004 | Traversal Origin | **runtime** | static proxy: every entry point in a traversal plan is an `Activity_Class` |
| ONT-005 | Systems Abstraction | static | `executes_via` targets only `Data Service`; only `Data Service` `masters` an `Abstracted Enterprise Entity` |
| ONT-006 | Cross-Model Sync | static | every `Outcome_Class` has an outgoing `measured_by` → `Measure` |
| ONT-007 | Vertical Encapsulation | **runtime** | static proxy: no horizontal edge leaves a subtree whose children are incomplete |
| ONT-008 | Boundary Strictness | static | `triggers`/`leads_to` connect same-tier nodes (tier from `attributes.type`) unless flagged as a domain crossing |
| ONT-009 | Decision Determinism | static (weak) | each `evaluate_decision` has exactly one `default` branch; branch conditions pairwise non-overlapping (SMT-lite on the `{property, operator, value}` DSL) |
| ONT-010 | Terminal Reachability | static | every horizontal path terminates at an `Outcome_Class` or a no-outgoing-edge node; no cycles without an exit |
| ONT-011 | Fact Classification | static | every `Fact` has an incoming `classifies` from a `Dimension` |
| ONT-012 | Async Acknowledgment | **runtime** | static proxy: nodes reached by `executes_via` have an `invoke_tool` execution and the caller's postcondition includes `trace_back` |
| ONT-013 | Agent Rule Contract | static | full `Agent_Rules_Schema` validation on all traversable nodes |

Phase 1 implements every **static** row and the **static proxy** of each runtime
row. A traversal simulator (Phase 6, optional) upgrades ONT-004/007/012 and
sharpens ONT-009.

---

## 6. Implementation plan

### Phase 0 — Foundations
**New package `src/ontology/`.**

- `src/ontology/models.py` — `MetaModel`, `MetaClass`, `EdgeRule`,
  `SystemicRule`, `OntologyNode`, `OntologyEdge`, `OntologyGraph`, `AgentRules`,
  `ConformanceFinding`. Dataclasses, matching the style of `src/models.py`.
- `src/ontology/loader.py` — parse both JSON files, validate against a
  `jsonschema` shape, build indexes (`by_id`, `out_edges`, `in_edges`,
  `by_meta_class`, `by_type`).
- **Two conventions the loader must normalise:**
  1. `["null"]` is the file's sentinel for "empty" — a one-element list holding
     the *string* `"null"`, not JSON `null`. Naive code treats it as a real
     value and ONT-001 silently passes on every Activity.
  2. A node has **two kinds**: its `meta_class` (`Activity_Class`) and its
     `attributes.type` (`Domain Activity`). The edge grammar's `valid_from` /
     `valid_to` mix both vocabularies freely — `performs` uses `Actor_Class`,
     `has_lifecycle_phase` uses `Core Activity`. Resolve each node to a **kind
     set** = `{meta_class} ∪ set(attributes.type)` and test membership against
     that. Getting this wrong changes the violation count.
- **Paths from config, not hardcoded** — the directory name
  `Ontology n metamodel` contains spaces. New `PipelineConfig` fields
  `ontology_path` / `metamodel_path` / `document_corpus_path`
  (`ONTO_ONTOLOGY_PATH` / `ONTO_METAMODEL_PATH` /
  `ONTO_DOCUMENT_CORPUS_PATH`), defaulting to the current locations.
  **Both input directories are gitignored** — they're supplied per
  deployment, not versioned (the IT4IT PDF alone is ~19 MB). The variables
  are already listed in `.env.example` under a PLANNED banner; drop the
  banner as each one lands in `load_from_env()`. Loader must fail with a
  clear "input not found at <path>, set ONTO_ONTOLOGY_PATH" message rather
  than a bare `FileNotFoundError`, since a fresh clone has neither folder.

**Deliverable:** `load_ontology()` / `load_metamodel()` round-trip both files
with zero data loss; `OntologyGraph` answers neighbour queries.

### Phase 1 — Metamodel conformance engine (Plane A)
**`src/ontology/conformance/`**

- `schema.py` — meta-class mandatory attributes, `type` enum membership,
  `Agent_Rules_Schema` conformance (ONT-013), execution-action vocabulary.
- `grammar.py` — edge grammar over the kind-set resolution from Phase 0.
  Every violation is also written to the **conflict registry** (Phase 1b) as a
  meta-model-vs-ontology disagreement awaiting human adjudication.
- `systemic.py` — one small class per rule, registered in a
  `SystemicRuleRegistry` keyed by `rule_id`, each declaring
  `severity ∈ {error, warning, info}` and `check_type ∈ {static, static_proxy}`.
  **Decision D2 confirmed — V4 is a work in progress**, so a rule whose governed
  meta-class has zero instances degrades from `error` to `warning` rather than
  firing at full severity. That is ONT-006 (no `Outcome_Class` to measure) and
  ONT-010 (39 of 40 Activities dead-end for want of Outcome nodes). Implement it
  as a declared `degrades_when_empty: [meta_class]` field on the rule, not as a
  special case buried in the checker — when Outcome nodes are eventually added,
  the rules escalate to `error` on their own with no code change.
- `consistency.py` — cross-representation checks not in any ONT-* rule but
  needed anyway: `next_pointer` ↔ `relationships` agreement (finding 6),
  dangling endpoints, duplicate ids.

**Reconcile the rule skew (finding 7)** by making the registry the single
authority over the **union** ONT-000..ONT-013, each entry recording which file
it came from. Emit an `info` finding when the two files' rule lists diverge, so
the skew is reported rather than silently resolved.

**Output:** `ConformanceFinding(rule_id, severity, subject_kind, subject_id,
message, evidence, remediation)`.

**Acceptance:** running against the shipped V4 reproduces section 4 exactly —
6 grammar violations, 45 `on_fail` violations, 5 undocumented actions, 39
dead-end activities, `reason ?` orphaned, `Escalation`→`API Endpoint` mismatch,
and clean passes on ONT-000/ONT-011/SIPOC-keys. Frozen as a golden fixture.

### Phase 1b — Conflict registry and adjudication queue
**Decision D1 confirmed:** the meta-model is authoritative — findings are
reported against the ontology and the validator never rewrites either file.
But a grammar violation is not always an ontology defect. Three of the six are
arguably meta-model gaps: `Cloud Watch` and `Cloud Logging` genuinely *are*
external systems, and `Runbook` genuinely *is* an abstracted entity. So each
disagreement is **persisted to its own store and escalated to a human**, rather
than silently counted as an error.

**`src/ontology/conflicts.py` → `ConflictRegistry`**, modelled directly on
`src/feedback/recorder.py` — same SQLite-with-`CREATE TABLE IF NOT EXISTS`
shape, same `_connect` helper, same record/query method split.

```sql
CREATE TABLE IF NOT EXISTS ontology_conflicts (
    conflict_id     TEXT PRIMARY KEY,   -- stable hash: rule_id + subject_id
    first_seen      DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen       DATETIME,
    rule_id         TEXT NOT NULL,      -- e.g. 'GRAMMAR' or 'ONT-005'
    subject_kind    TEXT NOT NULL,      -- 'node' | 'edge' | 'graph'
    subject_id      TEXT NOT NULL,      -- e.g. 'Log Monitor|executes_via|Cloud Watch'
    ontology_says   TEXT NOT NULL,      -- observed shape
    metamodel_says  TEXT NOT NULL,      -- required shape
    status          TEXT NOT NULL,      -- see lifecycle below
    resolution_note TEXT,
    resolved_by     TEXT,
    resolved_at     DATETIME,
    occurrences     INTEGER DEFAULT 1
);
```

**Status lifecycle:**

| Status | Meaning | Effect on the next run |
|---|---|---|
| `open` | Newly detected, not yet reviewed | Surfaced in the prompt queue; counted as `unreviewed` |
| `ontology_defect` | Confirmed — V4 is wrong | Reported as an **error** against the ontology |
| `metamodel_gap` | The blueprint is too narrow | Downgraded to **info**; registry stores the proposed grammar amendment |
| `accepted_exception` | Deliberate, documented deviation | Suppressed from the report, still visible in the registry |

**Idempotence is the whole point.** On each run, every conflict is keyed by
`conflict_id`; already-adjudicated ones bump `last_seen`/`occurrences` and reuse
the stored decision. **Only `open` conflicts prompt.** Without this, a 6-item
review queue re-asks the same six questions on every single run and gets ignored
within a day.

**Escalation surfaces** (same conflict, three front-ends):
- **CLI** — `scripts/validate_ontology.py --review` walks the open queue
  interactively; without the flag it runs non-interactively and reports the
  count of unreviewed conflicts. Non-interactive is the CI default.
- **API** — `GET /api/ontology/conflicts?status=open`,
  `POST /api/ontology/conflicts/{conflict_id}/resolve`, mirroring
  `api/routes/feedback.py`.
- **UI** — a review queue on the Ontology page, styled after the existing
  feedback/correction flow.

**A `metamodel_gap` resolution never edits `Final_Ontology_meta_model.json`.**
It records the amendment the blueprint *would* need (`executes_via.valid_to +=
["External System", "Abstracted Enterprise Entity"]`) and exposes it as a
proposed-diff export. Changing the authoritative blueprint stays a deliberate,
separate human act.

### Phase 2 — PDF ingestion (Plane B prerequisite)
- `src/ingestion/pdf_extractor.py` — `pdfplumber`-based, emitting per-page text
  plus tables, with a heading stack so each chunk carries
  `{source_file, page, section_path}`. Feed extracted tables through the
  existing `src/ingestion/table_extractor.py` and lists through
  `list_extractor.py` rather than reimplementing them.
- `DataIngestor.ingest_pdf(document_id, path)` alongside `ingest_document`,
  reusing the same chunk/embed/SVO path.
- **Page-level provenance is the point** — an ontology finding that says
  "unsupported" is only actionable if the supported ones cite
  `wb_incident_management.pdf p.7 §1.4.1`.
- **294-page IT4IT doc (decision D4 confirmed):** ingest behind an explicit
  opt-in flag with a page-range filter. The grounding corpus defaults to the two
  `wb_*` docs (24 pages), which
  is where the Event/Incident subtrees actually come from; IT4IT is a
  second-pass reference for the `Operations` / `Detect to Correct` tier.
- Add `pdfplumber` to `requirements-ml.txt` (already present in the `llmboi`
  conda env).

### Phase 3 — Ontology → assertion projection
**`src/ontology/projection.py`** turns the graph into verifiable claims. Four
claim kinds, each with stable ids and provenance back to the node/edge:

| Kind | Shape | Volume |
|---|---|---|
| `edge` | `(source.id, verbalize(edge.type), target.id)` | 85 |
| `sipoc` | `(activity, "takes input"/"produces output"/"is supplied by"/"serves", value)` | ~60 (after dropping `["null"]`) |
| `decision` | `(decision.id, "routes to on <condition>", branch.target)` | ~15 |
| `description` | `(node.id, "is described as", node.description)` | 74 |

≈ 230–240 assertions. At `top_k=5` with the cache warm this is minutes, not
hours; cold with transformer models it needs a progress-reporting batch runner.

**Verbalization matters.** `_build_assertion_query` is
`f"{subject} {relation} {object}"` (`src/engine.py:113`). Raw ontology ids
produce garbage queries — `filter out event ? triggers Create Event`. Ship an
edge-type→phrase map (`includes_process` → "includes the process",
`executes_via` → "is executed via", `performs_check` → "performs the check") and
strip trailing `?` from decision ids. This is the single highest-leverage knob
on Plane B precision.

Each projected assertion sets `polarity`/`rule_type` so the existing
`OntologyViolationValidator` negation handling stays meaningful.

### Phase 4 — Grounding run
**`src/ontology/compliance.py` → `OntologyComplianceValidator`**, the
orchestrator:

1. Run Plane A checkers → `List[ConformanceFinding]`.
2. Project assertions (Phase 3).
3. Ingest the corpus (Phase 2) once, then adjudicate corpus-wide.
4. Merge into one report.

**Engine change:** add `validate_assertions_corpus(assertion_list, document_ids=None, top_k)`
to `SVOVerificationEngine` — same body as `validate_triples_batch` minus the
ingest step, calling `adjudicate_triple(document_text=None, document_id=None)`,
which already searches unscoped. Keep `validate_triples_batch` untouched so
existing callers and tests don't move.

**Roll-up:** map per-assertion `supported/partial/contradicted/unknown` to a
per-node and per-edge grounding status, then to corpus coverage (% of ontology
nodes with ≥1 supporting chunk).

**Decision D5 confirmed — fail only on `contradicted`.** A node with no
document evidence is reported as a *coverage gap*, not a failure; structural
nodes like `Enterprise` and `Configuration Data` will never appear verbatim in
a process manual. The interesting bucket is the ontology edge the manual
actively disagrees with. Contradictions also feed the conflict registry — same
table, `rule_id = 'GROUNDING'` — so document-vs-ontology disagreements get the
same adjudication queue as meta-model-vs-ontology ones.

### Phase 5 — Report, CLI, API, UI
- **`ComplianceReport`** — conformance findings by severity, grounding verdicts,
  coverage stats, and a combined per-node status
  `{conformance: pass|fail, grounding: supported|unsupported|contradicted}`.
- **CLI** `scripts/validate_ontology.py`
  `--ontology --metamodel --documents Documents/ --plane a|b|both --out report.json`,
  matching the argument style of `scripts/validate_triples.py`.
- **API** — `POST /api/ontology/validate`, `GET /api/ontology/report/{id}`,
  `GET /api/ontology/graph` (nodes + edges + status, for the viewer), plus the
  Phase 1b conflict endpoints. New router in `api/routes/ontology.py`, wired in
  `api/app.py`, schemas in `api/schemas.py`.
- **Frontend** — an Ontology page: graph view coloured by the two axes, a
  findings table filterable by `rule_id`/severity, a node drawer showing the
  cited PDF pages, and the **conflict review queue** with one-click
  `ontology_defect` / `metamodel_gap` / `accepted_exception` resolution. Reuses
  the existing `components/charts` primitives, the trace-detail toggle pattern
  from the verdict view, and the correction-flow styling from the feedback page.

### Phase 6 — Optional: traversal simulator
Upgrades the three `static_proxy` rules to real checks. Executes the
`agent_rules` DSL (`precondition` conditions, `evaluate_decision` branches,
`traverse_dfs`, `invoke_tool`) over a mock payload from an entry Activity, and
asserts ONT-004 (origin), ONT-007 (encapsulation), ONT-009 (single path),
ONT-012 (blocking on `executes_via`). Deferrable — Phase 1's proxies catch the
current defects without it.

### Phase 7 — Tests, config, docs
- **Golden regression** — section 4's findings as a frozen fixture.
  **The inputs are gitignored** (`Documents/`, `Ontology n metamodel/`), so this
  test cannot read them from a clean checkout. Commit
  `tests/fixtures/ontology_conformance_baseline.json` holding the expected
  finding set *plus a SHA-256 of the ontology and meta-model files it was
  derived from*, and have the test:
  - **skip with an explicit reason** when the source files are absent (not
    silently pass — a skipped golden test that reads as green is worse than no
    test);
  - **fail loudly** when the files are present but their hashes don't match the
    baseline, so an ontology revision surfaces as "baseline is stale, re-bless
    it" rather than as a confusing diff in the findings list.
  Regenerate via `scripts/validate_ontology.py --bless-baseline`.
- **Synthetic fixtures** — a minimal ontology with one deliberate violation per
  ONT-* rule, so each checker is tested in isolation rather than only against
  V4's incidental defects.
- **Grounding smoke test** — the 10-page Event Management PDF against the
  Event Management subtree; small enough for CI.
- **Conflict-registry idempotence test** — run conformance twice against an
  unchanged ontology and assert the second run prompts for zero conflicts and
  bumps `occurrences` instead of inserting duplicates. This is the property most
  likely to regress silently.
- Note: five tests already fail on a clean tree — check them against the
  known-baseline list before treating any failure as a regression.
- Config fields: `ontology_path`, `metamodel_path`,
  `enable_metamodel_conformance`, `enable_ontology_grounding`,
  `conformance_severity_threshold`, `ontology_claim_kinds`,
  `document_corpus_path`, `include_it4it_corpus` (default `False`),
  `conflict_db_path` (default `conflicts.db`), `enable_conflict_registry`.
  Mirror into `.env.example` — `PipelineConfig.load_from_env()` in
  `src/config.py` stays the source of truth. Note `_resolve_derived_db_paths()`
  in `src/config.py:145` already handles sibling DB paths; `conflicts.db` should
  follow the same resolution so it lands next to `feedback.db`.
- `docs/ONTOLOGY_COMPLIANCE.md` (usage) + a README section.

---

## 7. Sequencing

```
Phase 0  Foundations ──┬── Phase 1  Conformance (Plane A) ── Phase 1b  Conflict registry ─┐
                       │                                                                  │
                       └── Phase 3  Projection ──┐                                        │
                                                 ├─ Phase 4  Grounding ─┬─ Phase 5  Report/API/UI
Phase 2  PDF ingestion ──────────────────────────┘                      │                 │
                                                                        └─────────────────┤
                                                    Phase 6 (optional) ───────────────────┤
                                                    Phase 7 Tests/docs ───────────────────┘
```

Phase 1 is the fastest path to visible value: it is self-contained, needs no
documents or models, and already has seven real findings waiting for it.
Phase 1b should land with it rather than after — the registry is what turns
those findings from a static list into a queue you can actually work through,
and retrofitting stable `conflict_id`s later means re-adjudicating everything.
Phases 2+3 are independent of each other and can proceed in parallel with 1.

---

## 8. Decisions (resolved 2026-08-26)

All five are settled. Recorded here because they change what the checkers *do*,
not just how they're built — revisit them before changing any severity.

**D1 — Meta-model is authoritative, disagreements are logged and escalated.**
When the blueprint's grammar and V4 conflict, the finding is reported against
the ontology and neither file is auto-edited. But every such conflict is also
persisted to a dedicated `ontology_conflicts` store and surfaced for human
adjudication as `ontology_defect` / `metamodel_gap` / `accepted_exception`.
Three of the six current violations are plausibly blueprint gaps rather than
ontology errors, so counting them as flat errors would be wrong. See **Phase 1b**.

**D2 — V4 is incomplete; zero-instance rules degrade to `warning`.**
ONT-006 and ONT-010 report as warnings, not errors, while `Outcome_Class` and
`Actor_Class` have no instances. Implemented declaratively via
`degrades_when_empty` so the rules self-escalate once those nodes are added.

**D3 — Rule registry takes the union, reports the divergence.**
The registry covers ONT-000..ONT-013 (the meta-model's 8 ∪ the ontology's 13),
recording each rule's source file, and emits an `info` finding that the two
files' rule lists disagree. The meta-model file should be bumped to v2.2 to
match the ontology — flagged, not done automatically.

**D4 — Grounding corpus defaults to the `wb_*` manuals; IT4IT behind a flag.**
24 pages instead of 318. IT4IT is available via `include_it4it_corpus` for a
second pass over the `Operations` / `Detect to Correct` tier.

**D5 — Grounding fails only on `contradicted`.**
No-evidence is a coverage gap, not a failure. Contradictions route into the same
conflict registry as D1, under `rule_id = 'GROUNDING'`.

### Still genuinely open

Not blockers, but they'll want an answer before Phase 5:

- **Who adjudicates?** The registry has a `resolved_by` column but no auth. If
  more than one person works the queue, that needs to come from somewhere real.
- **Does a `metamodel_gap` resolution ever get applied?** Right now it produces
  a proposed diff and stops. Whether that becomes a PR against
  `Final_Ontology_meta_model.json` is a process question, not a code one.

## 9. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Demo-tier "semantic" retriever is Jaccard-on-tokens, not embeddings | Ontology ids paraphrased in prose won't retrieve | Run Plane B with `ONTO_EMBEDDING_MODEL=transformer`; treat demo-tier grounding as smoke-test only |
| ~240 assertions × transformer adjudication | Long cold runs | Verdict cache is keyed on document fingerprint (`src/engine.py:814`) and already handles this; add batch progress reporting |
| `["null"]` sentinel misread as a value | ONT-001 passes on every Activity, silently | Normalise in the loader; unit-test the sentinel explicitly |
| Kind-set resolution done wrong | Wrong violation counts, both directions | Golden fixture from section 4 pins it |
| Scope creep into ontology *authoring* | Plan becomes an editor, not a validator | Validator reports and proposes; it never rewrites the JSON |
| Unstable `conflict_id` (e.g. hashing a mutable label) | Every run re-opens already-adjudicated conflicts; the queue becomes noise and gets ignored | Key on `rule_id + subject_id` only; idempotence test in Phase 7 |
| Review queue never gets worked | Conflicts pile up as `unreviewed`, conformance has no meaningful pass/fail | Report unreviewed count as a first-class metric, not buried in the findings list |

---

## 10. What changed during implementation

The plan survived contact largely intact. Seven things it did not anticipate.

### 10.1 An eighth ontology defect
Decision node `is major incident ?` has a branch targeting `trace_back` - a
postcondition *action name*, not a node. Section 4's dry run missed it because
it only checked `relationships` and `next_pointer`, never decision branches.
Now caught by `CONSISTENCY-BRANCH-TARGET`; projection skips such branches,
since a claim about a non-existent node cannot be grounded.

### 10.2 The undocumented-action count is 7, not 5
Section 4 said five. It is seven - `evaluate_decision` (6 uses) and `halt` (1)
are also absent from the blueprint. More importantly, the blueprint declares
that vocabulary as prose hedged with **"e.g."** - an *open* set - while
`on_fail` is a JSON list, a *closed* one. Reporting the former as hard errors
would fail the model on the strength of an abbreviation. Split into:

* `ONT-013` - `on_fail` violations, **error**, 45 findings;
* `ONT-013-VOCAB` - undocumented verbs, **warning**, 7 findings.

The loader records `execution_vocabulary_open`, so a stricter blueprint
revision that enumerates actions as a list escalates these to errors with no
code change.

### 10.3 ONT-001 fails on 27 of 27 eligible activities
Every Activity with a transition is missing `input` and/or `output`. That is a
population gap in a work-in-progress model, not 27 independent defects, so
ONT-001 is registered at **warning** with the ratio surfaced in the report.

### 10.4 A chunk explosion that would have poisoned the corpus
30 pages of IT4IT produced **15,699 chunks**: 98% of "sentences" on
table-of-contents pages were the two-character string `" ."`, because the
shared sentence splitter reads a dot leader as dozens of sentences. Each would
have become a row in the chunk store and a candidate in every retriever. Fixed
with dot-leader normalization and a content filter **on the PDF path only** -
`ingest_document` shares that splitter and existing callers depend on it.
IT4IT p1-30: 15,699 -> **622** chunks; the two process manuals barely moved
(142->138, 207->207).

### 10.5 Grounding needs production backends - two independent ceilings
Plane B runs end to end but produces **zero `supported` verdicts**, and the
demo tier cannot be made to produce them:

1. the demo "semantic" retriever is Jaccard over token sets, so paraphrases are
   unreachable - and `ONTO_EMBEDDING_MODEL=transformer` does *not* help,
   because the demo retriever ignores embeddings;
2. `HeuristicEvidenceSpanClassifier` decides `matched_relation` by literal
   substring, and a verbalized predicate like "includes the process" never
   appears verbatim in a human-written manual.

`ONTO_EVIDENCE_SPAN_CLASSIFIER=nli` is **not** a workaround: measured on this
corpus it manufactures false contradictions, labelling an unrelated RACI-table
row as *refuting* a claim at 1.00 confidence. Under D5 that converts a cosmetic
problem into a wrong answer. The report self-labels `grounding.confidence: low`
on the demo tier.

### 10.6 D4's default costs real coverage
Only **28 of 74** node labels appear verbatim in the `wb_*` corpus. The missing
ones - `Detect to Correct`, `Assure`, `Service Monitor`, `Log Monitor`,
`Runbook`, `Business Criticality` - are present in IT4IT, which D4 excludes by
default. Including it moved the numbers only slightly (129->139 partial),
because 10.5's ceilings dominate. **D4 is worth revisiting once real backends
are wired**: the ontology genuinely spans both tiers, with its upper levels
drawn from IT4IT and its process levels from the process manuals.

A `vocabulary_gap` diagnostic now reports this directly, separating "the corpus
never mentions this term" (a corpus problem) from "present but unmatched" (a
retrieval problem) - opposite fixes, previously indistinguishable among the
`unknown` verdicts.

### 10.7 Where the code landed

| Module | Purpose |
|---|---|
| `src/ontology/models.py`, `loader.py` | Typed models; sentinel + kind-set normalization |
| `src/ontology/conformance/` | 18 rules across schema / grammar / systemic / consistency |
| `src/ontology/conflicts.py` | `ConflictRegistry`, adjudication queue, amendment proposals |
| `src/ontology/projection.py` | 252 claims over 4 kinds, with verbalization |
| `src/ontology/compliance.py` | Two-plane orchestrator |
| `src/ontology/report.py` | `ComplianceReport`, roll-ups, coverage, vocabulary gap |
| `src/ingestion/pdf_extractor.py` | pdfplumber extraction with page/section provenance |
| `src/engine.py` | `validate_assertions_corpus`, `corpus_fingerprint` |
| `api/routes/ontology.py` | 5 endpoints |
| `frontend/src/pages/OntologyPage.tsx` | Two-axis view, findings table, review queue |
| `scripts/validate_ontology.py` | CLI incl. `--review`, `--bless-baseline` |

**Tests:** 700 passing, 1 pre-existing failure
(`test_negation_is_reported_for_the_malaria_sentence`, confirmed failing on a
pristine HEAD worktree). Roughly 240 of those are new.

### 10.8 Current headline numbers

```
conformance: FAIL  (57 error, 76 warning, 1 info)   134 findings
  GRAMMAR 6 | ONT-001 27 | ONT-003 1 | ONT-005 3 | ONT-009 2
  ONT-010 39 (degraded) | ONT-012 1 | ONT-013 45 | ONT-013-VOCAB 7
  CONSISTENCY-NEXT-POINTER 1 | CONSISTENCY-BRANCH-TARGET 1 | RULESET-SKEW 1
grounding:   PASS  (0 supported, 128 partial, 0 contradicted, 124 unknown)
             confidence: low - see 10.5
vocabulary:  28/74 node labels appear in the corpus (37.8%)
```
