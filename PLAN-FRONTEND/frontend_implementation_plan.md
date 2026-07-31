# Frontend Rebuild: React SPA for Ontovalidator

## Context

The backend (branch `claude/plan-folder-overhaul-dd159a`) now returns a much richer verdict payload than the current frontend can show: per-retriever `retrieval_pathway`, escaped `annotated_html` with negation analysis, a full `scoring_breakdown` and `decision_thresholds` explanation, `rejected_evidence`, temporal status per evidence span, and a `feedback_id` for correcting verdicts. There's also a feedback analysis endpoint (confusion matrix, retriever accuracy, recommendations) with no UI at all today.

The current frontend (`frontend/index.html` + `app.js` + `styles.css`) is a single-file vanilla-JS page that only renders the pre-enhancement fields (label, score, rationale, a flat evidence list). It has no build tooling — FastAPI mounts `frontend/` directly as static files (`api/app.py`: `StaticFiles(directory=FRONTEND_DIR, html=True)` at `/`).

Decisions made for this plan: rebuild in **React with a build step**, target **full parity** with all 8 backend enhancements, and render everything **always-expanded** (no accordions) on a **single scrolling page** for validation, with the feedback dashboard and cache/health info as **separate routes**.

Goal: a componentized SPA that surfaces every field the backend already computes, replacing the static mount with a Vite build output, without touching backend logic beyond one path change.

---

## Tech choices

- **Vite + React + TypeScript**. Vite needs no config for a FastAPI-adjacent static deploy — `vite build` emits a `dist/` directory that's a drop-in replacement for the current static mount.
- **React Router** (`react-router-dom`) for `/validate` (default), `/feedback`, `/health` (cache + backend status).
- **No CSS framework** — port the existing dark palette (CSS variables in `frontend/styles.css`: `--bg`, `--panel`, `--border`, `--text`, `--muted`, `--accent`, `--green`, `--red`, `--amber`, `--gray`) into a `theme.css`, so the new app looks like a continuation of the current one rather than a reskin. Reuse the card/button/label-dot conventions already established.
- **No extra data-fetching library** — the API surface is 4 endpoints with no pagination; plain `fetch` wrapped in a small `src/api/client.ts` is enough. Avoid pulling in React Query for this scope.
- Dev server proxies `/validate`, `/config`, `/health`, `/feedback/*` to the FastAPI backend (`vite.config.ts` `server.proxy`), so `npm run dev` works against a locally running API without CORS issues (the backend already sets `allow_origins=["*"]` for prod anyway).

## New directory layout

```
frontend/                      # becomes the Vite project root
  index.html                   # Vite entry HTML (replaces the static one)
  package.json / vite.config.ts / tsconfig.json
  src/
    main.tsx                   # ReactDOM root, router setup
    theme.css                  # ported CSS variables + resets
    api/
      client.ts                # fetch wrappers: validate(), getConfig(), getHealth(), submitCorrection(), getFeedbackAnalysis()
      types.ts                 # TS interfaces mirroring api/schemas.py exactly (VerdictOut, EvidenceOut, RejectedEvidenceOut, SummaryOut, ConfigResponse, HealthResponse, FeedbackAnalysisResponse, CorrectionRequest/Response)
    pages/
      ValidatePage.tsx          # the main workflow (form + results), default route
      FeedbackPage.tsx          # analysis dashboard
      HealthPage.tsx            # backend health + cache_hits history
    components/
      validate/
        DocumentForm.tsx        # raw_text textarea + settings (embedding_model/svo_extractor/top_k) + triples editor
        TriplesEditor.tsx       # add/remove triple rows (port of triple-row grid)
        ResultsSummary.tsx      # summary strip (total/supported/contradicted/partial/unknown/avg_score/cache_hits)
        VerdictCard.tsx         # one triple's full verdict, always-expanded sections
        ScoringBreakdown.tsx    # renders scoring_breakdown + decision_thresholds
        RejectedEvidenceList.tsx
        EvidenceItem.tsx        # one evidence span: annotated_html, retrieval_pathway, negation_analysis, component_matches, temporal_status
        RetrievalPathway.tsx    # per-retriever rank/score/reason + fusion_explanation
        FeedbackCorrectionForm.tsx  # inline correction UI on each VerdictCard, posts to /feedback/correct
      feedback/
        ConfusionMatrix.tsx
        RetrieverPerformanceTable.tsx
        RecommendationsList.tsx
      shared/
        Card.tsx, Button.tsx, LabelDot.tsx, ErrorBanner.tsx, LoadingSpinner.tsx
  dist/                         # build output (gitignored), mounted by FastAPI
```

`frontend/` currently holds the static files directly; those get replaced by the Vite project (old `index.html`/`app.js`/`styles.css` removed once parity is confirmed).

## Backend touch point (minimal, explicit)

`api/app.py` currently does:
```python
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
```
Change `FRONTEND_DIR` to point at `frontend/dist` (the Vite build output) instead of `frontend/`. This is the only backend edit — everything else is additive on the frontend side. No other API/schema/engine changes.

## Component design per enhancement (always-expanded)

1. **Retrieval pathway** (`RetrievalPathway.tsx`) — three-column layout (lexical / semantic / graph), each showing rank, score, reason; null rank/score renders "not retrieved" in muted text. Fusion score + fusion_explanation shown below as a combined summary line.
2. **Chunk annotation** (`EvidenceItem.tsx`) — `annotated_html` rendered via `dangerouslySetInnerHTML` (safe: backend already HTML-escapes via `html.escape` before marking, per `src/annotation/annotator.py`). `negation_analysis` (negation_detected badge + keywords + scope) and `component_matches` (three colored check/cross icons for S/V/O) shown inline below the marked-up text.
3. **Scoring transparency** (`ScoringBreakdown.tsx`) — render every key of `scoring_breakdown` as a labeled row (baseline, support/partial/refute components, agreement_bonus, raw_score, final_score, optional adjustment_reason/lm_judge_label), followed by `decision_thresholds` as three explanation lines (contradicted_rule / supported_rule / chosen_label).
4. **Rejected evidence** (`RejectedEvidenceList.tsx`) — always-expanded list under each verdict, same visual weight as evidence but visually muted/struck-through styling to distinguish "considered but excluded."
5. **Feedback loop** (`FeedbackCorrectionForm.tsx` + `FeedbackPage.tsx`) — a small inline form on every `VerdictCard` ("Correct this verdict": label dropdown + optional reason, posts `{feedback_id, actual_label, reason}` to `/feedback/correct`); on 404 (`verdict_not_found`) falls back to resending the full field set the verdict already has client-side. `FeedbackPage` calls `/feedback/analysis?days=N` (day-range selector) and renders `ConfusionMatrix`, `RetrieverPerformanceTable`, `RecommendationsList` from the response's `summary`/`error_analysis`/`retriever_performance`/`recommendations`. Since those three dashboard fields are untyped `Dict[str, Any]` in the schema, `FeedbackPage` will defensively render via a generic key/value tree fallback for any unexpected nested shape, rather than assuming exact keys — **before finalizing this page**, read `src/feedback/dashboard.py::compute_metrics` once during implementation to nail exact keys and build typed interfaces instead of the generic fallback.
6. **Caching** — no dedicated cache endpoint exists. `ResultsSummary.tsx` shows `summary.cache_hits` from `/validate`. `HealthPage.tsx` shows `backend_status`/`/health` output (per-backend latency/health) since that's the only other operational signal available; label it "Backend Health" rather than implying cache stats live there.
7. **Multi-modal ingestion** — `chunk_types` histogram (from `/validate` response) rendered as a small bar/badge row above the verdicts on `ValidatePage` (e.g. "text: 12, table_row: 3, list_item: 2"). Evidence items also tag their source chunk type via `metadata` if surfaced — no explicit chunk_type in `EvidenceOut` currently, so this stays document-level, not per-evidence.
8. **Temporal reasoning** — `temporal_status` and `chunk_timestamp` rendered as a small badge on each `EvidenceItem` (e.g. "outdated · 1995-06-15" in amber, "current" in green, hidden entirely when null/`unscoped`/`undated` to avoid noise).

## Error handling

Port the existing pattern from `app.js`: the backend's error envelope is double-nested (`{"error": {"error": "...", "detail": "..."}}` per `api/errors.py`). `client.ts` normalizes this into a single `{message: string}` shape so components never deal with the nesting directly. `ErrorBanner.tsx` is a dismissible top banner, same UX as today.

## Build/dev workflow

```bash
cd frontend
npm install
npm run dev      # Vite dev server on 5173, proxies API calls to FastAPI on 8000
npm run build    # emits frontend/dist, consumed by FastAPI's StaticFiles mount
```

## Verification

1. `npm run build` succeeds with no TypeScript errors.
2. Start FastAPI (`uvicorn api.app:app`) pointed at `frontend/dist`; load `/` and confirm the built SPA serves.
3. Manual pass through `/validate`: submit a document + 2-3 triples covering each label (supported/contradicted/partial/unknown) and confirm every section renders — retrieval pathway (including a `null` retriever case), annotated HTML with negation, scoring breakdown, rejected evidence, temporal badges (use a doc with a `Published:` date and an assertion `temporal_scope` to trigger `outdated`/`future`), and multi-modal chunk_types (ingest text containing a bullet list and an HTML table).
4. Submit a correction via the inline form on a verdict, confirm `POST /feedback/correct` succeeds, then load `/feedback` and confirm the confusion matrix reflects it.
5. Load `/health` and confirm backend statuses render.
6. Confirm the dismissible error banner triggers correctly on a deliberately malformed request (e.g. empty `raw_text`).

---

## Open item to resolve before/during implementation

`src/feedback/dashboard.py::compute_metrics` was not read during this planning pass — its `summary` / `error_analysis` / `retriever_performance` return shapes are untyped `Dict[str, Any]` at the API schema level. Read that file first when building `FeedbackPage.tsx` to get exact keys for typed interfaces instead of the generic key/value fallback described above.
