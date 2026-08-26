# Ontology Compliance — usage

Validates an enterprise ontology against **its meta-model** and **its source
documents**. Design rationale and the decision log live in
`ONTOLOGY_COMPLIANCE_PLAN.md`; this is how to run it.

## Inputs

Both directories are **gitignored** — supplied per deployment, not versioned
(the IT4IT PDF alone is ~19MB). Point the pipeline at them with:

```bash
ONTO_ONTOLOGY_PATH="Ontology n metamodel/Ontology_V4_description.json"
ONTO_METAMODEL_PATH="Ontology n metamodel/Final_Ontology_meta_model.json"
ONTO_DOCUMENT_CORPUS_PATH="Documents/"
```

A missing input fails with `input not found at <path>, set ONTO_ONTOLOGY_PATH`
rather than a bare `FileNotFoundError` — on a fresh clone that's the normal
first run, not an edge case.

## The two planes

| Plane | Question | Needs | Runtime |
|---|---|---|---|
| **A — conformance** | Does the ontology obey its meta-model? | the two JSON files | ~50ms |
| **B — grounding** | Do the source documents support its claims? | + PDFs, engine, models | minutes |

They are reported separately and never averaged. "Conformant but contradicted
by the process manual" is the finding a reviewer most wants, and a combined
score is exactly what would hide it.

## CLI

```bash
# Conformance only — the fastest useful thing, no corpus needed.
python scripts/validate_ontology.py --plane a

# Both planes, full JSON report.
python scripts/validate_ontology.py --documents Documents/ --out report.json

# Work the conflict queue interactively.
python scripts/validate_ontology.py --plane a --review

# CI gate.
python scripts/validate_ontology.py --plane a --fail-on-findings
```

Useful flags: `--severity {error,warning,info}`, `--claim-kinds edge,sipoc`,
`--include-it4it`, `--top-k N`, `--no-registry`, `--bless-baseline`.

## HTTP API

| Endpoint | Purpose |
|---|---|
| `POST /api/ontology/validate` | Run either or both planes, return the report |
| `GET  /api/ontology/graph` | Nodes + edges for a viewer, no checks run |
| `GET  /api/ontology/conflicts?status=open` | The adjudication queue |
| `POST /api/ontology/conflicts/{id}/resolve` | Adjudicate one conflict |
| `GET  /api/ontology/amendments` | Meta-model changes implied by `metamodel_gap` rulings |

Errors nest under `error` (`{"error": {"error": ..., "detail": ...}}`), the
shape `frontend/src/api/client.ts` already parses.

## The conflict registry

The meta-model is authoritative (decision D1), but a grammar violation is not
always an ontology defect — `Cloud Watch` genuinely *is* an external system.
So each disagreement is persisted to `conflicts.db` and escalated for a human
ruling:

| Status | Meaning | Effect on the report |
|---|---|---|
| `open` | not yet reviewed | reported as-is, counted as unreviewed |
| `ontology_defect` | the ontology is wrong | stays an **error** |
| `metamodel_gap` | the blueprint is too narrow | downgraded to **info** |
| `accepted_exception` | deliberate deviation | suppressed (still in the registry) |

**Rulings are idempotent.** Conflicts key on `rule_id + subject_id` only, so
re-running validation bumps `occurrences` and leaves the ruling alone. Without
that, a six-item queue would re-ask the same six questions every run and be
ignored within a day.

`GET /amendments` (and `--review`) produce a **proposed** blueprint diff.
Nothing ever writes to `Final_Ontology_meta_model.json`.

## Reading the output

```
Ontology 2.2 vs meta-model 2.1
  conformance: FAIL  (57 error, 76 warning, 1 info)
  unreviewed conflicts: 16 (run with --review)
  grounding:   PASS  (0 supported, 128 partial, 0 contradicted, 124 unknown)
  coverage:    0/74 nodes (0.0%), 0/85 edges (0.0%)
  [!] demo-tier retrieval: 'supported' is not reachable ...
  vocabulary:  28/74 node labels appear in the corpus (37.8%); 46 never mentioned
```

- **conformance FAIL** — at least one `error`. Warnings and info don't fail.
- **grounding PASS** — decision D5: only `contradicted` fails. A claim with no
  evidence is a coverage gap, not a defect; `Enterprise` will never appear
  verbatim in a process manual.
- **vocabulary** — separates the two reasons a claim reads `unknown`: a term
  the corpus never mentions is a *corpus* problem, a term that is present but
  unmatched is a *retrieval* problem. Opposite fixes.

## Known limitation: grounding needs production backends

**Plane B does not currently produce any `supported` verdicts on this corpus,
and the demo tier cannot make it do so.** Two independent ceilings:

1. The demo "semantic" retriever is Jaccard over token sets, not embeddings
   (`SQLiteSemanticRetriever`), so a claim phrased differently from the source
   prose is unreachable. `ONTO_EMBEDDING_MODEL=transformer` does **not** fix
   this — the demo retriever ignores embeddings.
2. `HeuristicEvidenceSpanClassifier._compute_match_flags` decides
   `matched_relation` by literal substring. A verbalized predicate like
   "includes the process" essentially never appears verbatim in a
   human-written manual, so `matched_relation` is always false and
   `supported` is unreachable by construction.

Both must lift together. That means the Elasticsearch/Milvus tier
(`ONTO_ES_ENABLED=true`, `ONTO_MILVUS_ENABLED=true`).

**Do not reach for `ONTO_EVIDENCE_SPAN_CLASSIFIER=nli` as a workaround.**
Measured on this corpus, it manufactures false contradictions — it confidently
labels an unrelated RACI-table row as *refuting* "Event Management includes
the process Event Filtering" at 1.00 confidence. Since D5 makes contradiction
the only failing condition, that turns a cosmetic problem into a wrong answer.

The report labels this itself: `grounding.confidence` is `low` on the demo
tier. Treat conformance as the measurement and grounding as a smoke test until
real backends are wired.

## Regression baseline

`tests/fixtures/ontology_conformance_baseline.json` pins the current 134
findings **plus SHA-256 of the two inputs**, because the inputs are gitignored
and CI has only the fixture.

- inputs absent → tests **skip** with an explicit reason (a golden test that
  silently passes is worse than none);
- inputs present but hash-mismatched → tests **fail** with "re-bless it",
  rather than an unexplained diff in a 134-line list.

```bash
python scripts/validate_ontology.py --plane a --bless-baseline
```
