# Frontend Rebuild: React SPA for Ontovalidator

## Context

The backend (branch `claude/plan-folder-overhaul-dd159a`) now returns a much richer verdict payload than the current frontend can show: per-retriever `retrieval_pathway`, escaped `annotated_html` with negation analysis, a full `scoring_breakdown` and `decision_thresholds` explanation, `rejected_evidence`, temporal status per evidence span, and a `feedback_id` for correcting verdicts. There's also a feedback analysis endpoint (confusion matrix, retriever accuracy, recommendations) with no UI at all today.

The current frontend (`frontend/index.html` + `app.js` + `styles.css`) is a single-file vanilla-JS page that only renders the pre-enhancement fields (label, score, rationale, a flat evidence list). It has no build tooling — FastAPI mounts `frontend/` directly as static files (`api/app.py`: `StaticFiles(directory=FRONTEND_DIR, html=True)` at `/`).

Decisions made for this plan: rebuild in **React with a build step**, target **full parity** with all 8 backend enhancements, render everything **always-expanded** (no accordions) on a **single scrolling page** for validation, with the feedback dashboard and health/system info as **separate routes** — and present every naturally quantitative payload as a proper **visualization** (charts, heatmap, score bars), not just text tables.

Goal: a componentized SPA that surfaces every field from every API endpoint, replacing the static mount with a Vite build output, without touching backend logic beyond one path change.

---

## Tech choices

- **Vite + React + TypeScript**. Vite needs no config for a FastAPI-adjacent static deploy — `vite build` emits a `dist/` directory that's a drop-in replacement for the current static mount.
- **React Router** (`react-router-dom`) for `/validate` (default), `/feedback`, `/health` (backend status + system configuration).
- **Recharts** for Cartesian/radial charts (verdict-label bars, chunk-type histogram, retriever accuracy bars, accuracy donut). The confusion-matrix heatmap stays hand-rolled CSS grid (Recharts has no heatmap primitive) and micro-bars (scoring contributions, pathway scores, latencies) stay plain styled divs — Recharts only where it earns its weight. Route-level `React.lazy` code-splitting keeps chart bundles off the initial load.
- **No CSS framework** — port the existing dark palette (CSS variables in `frontend/styles.css`: `--bg`, `--panel`, `--border`, `--text`, `--muted`, `--accent`, `--green`, `--red`, `--amber`, `--gray`) into a `theme.css`. Charts consume the same palette via a small `chartTheme.ts`; add chart-specific styles (heatmap cells, bars, gauges) to `theme.css`.
- **No extra data-fetching library** — the API surface is 5 endpoints with no pagination; plain `fetch` wrapped in a small `src/api/client.ts` is enough. Avoid pulling in React Query for this scope.
- Dev server proxies `/validate`, `/config`, `/health`, `/feedback/*` to the FastAPI backend (`vite.config.ts` `server.proxy`), so `npm run dev` works against a locally running API without CORS issues (the backend already sets `allow_origins=["*"]` for prod anyway).

## New directory layout

```
frontend/                      # becomes the Vite project root
  index.html                   # Vite entry HTML (replaces the static one)
  package.json / vite.config.ts / tsconfig.json
  src/
    main.tsx                   # ReactDOM root, router setup (lazy-loaded routes)
    theme.css                  # ported CSS variables + resets + chart styles
    api/
      client.ts                # fetch wrappers: validate(), getConfig(), getHealth(force?), submitCorrection(), getFeedbackAnalysis()
      types.ts                 # TS interfaces mirroring api/schemas.py exactly, incl. typed feedback-analysis payloads
    pages/
      ValidatePage.tsx          # main workflow (form + results), default route
      FeedbackPage.tsx          # analysis dashboard (charts + heatmap)
      HealthPage.tsx            # backend health + system configuration
    components/
      charts/                   # visualization layer (shared, dark-themed)
        chartTheme.ts           # palette mapping to CSS vars, dark tooltip styling
        LabelDistributionChart.tsx   # Recharts bar chart of verdict labels
        ChunkTypeHistogram.tsx       # Recharts bar chart of chunk_types
        AccuracyDonut.tsx            # Recharts RadialBarChart of system_accuracy
        RetrieverAccuracyChart.tsx   # Recharts paired horizontal bars: accuracy vs error rate
        ConfusionHeatmap.tsx         # CSS-grid heatmap, green diagonal / red off-diagonal
        ScoreContributionBars.tsx    # signed div-bars per scoring_breakdown numeric key
        PathwayMiniBars.tsx          # 0-1 score bars per retriever + fusion gauge
        LatencyBars.tsx              # div-bars of per-backend latency_ms
      validate/
        DocumentForm.tsx        # raw_text textarea + settings + triples editor
        TriplesEditor.tsx       # add/remove triple rows (port of triple-row grid)
        ResultsSummary.tsx      # stat chips + LabelDistributionChart + ChunkTypeHistogram
        VerdictCard.tsx         # one triple's full verdict, always-expanded sections
        ScoringBreakdown.tsx    # contribution bars + decision_thresholds lines
        RejectedEvidenceList.tsx
        EvidenceItem.tsx        # annotated_html, retrieval_pathway, negation_analysis, component_matches, temporal_status
        RetrievalPathway.tsx    # per-retriever rank/score bars/reason + fusion_explanation
        FeedbackCorrectionForm.tsx  # inline correction UI, posts to /feedback/correct
      feedback/
        ConfusionMatrix.tsx     # wraps ConfusionHeatmap + legend + most-common-error callout
        RetrieverPerformanceTable.tsx  # table + RetrieverAccuracyChart, best/worst badges
        RecommendationsList.tsx
      shared/
        Card.tsx, Button.tsx, LabelDot.tsx, ErrorBanner.tsx, LoadingSpinner.tsx, StatChip.tsx
  dist/                         # build output (gitignored), mounted by FastAPI
```

`frontend/` currently holds the static files directly; those get replaced by the Vite project (old `index.html`/`app.js`/`styles.css` removed once parity is confirmed).

## Backend touch point (minimal, explicit)

`api/app.py` currently does:
```python
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
```
Change `FRONTEND_DIR` to point at `frontend/dist` (the Vite build output) instead of `frontend/`. This is the only backend edit — everything else is additive on the frontend side. No other API/schema/engine changes. (A "corrections over time" trend chart is deliberately out of scope: no endpoint exposes a time series today; adding `/feedback/timeline` is noted as future work.)

## Endpoint integration map

Every field of every endpoint has a home in the UI:

| Endpoint | Field(s) | Rendered in |
|---|---|---|
| `POST /validate` | `ingestion_status`, `chunks_ingested`, `svos_extracted` | ingestion info line above summary |
| | `chunk_types` | `ChunkTypeHistogram` above verdicts |
| | `summary.*` | StatChips + `LabelDistributionChart` |
| | `verdicts[]` (labels, scores, evidence, breakdown, rejected, feedback_id) | `VerdictCard` tree |
| | `backend_status` | status dots beside page title |
| `GET /config` | `backend_mode`, `sqlite_path`, model names, `validator_name`, `enable_lm_judge/classifier`, `available_*` lists | System Configuration card on `HealthPage` |
| | `backend_status` | status dots in the same card |
| `GET /health?force=` | `overall_status`, `backends{}` (`latency_ms`, `error_message`, `timestamp`) | status banner + per-backend cards with `LatencyBars` |
| | `recommendations[]` | health recommendations list |
| `POST /feedback/correct` | request/response | `FeedbackCorrectionForm` on each verdict |
| `GET /feedback/analysis?days=N` | `summary.total_corrections/system_accuracy/window_days` | stat chips + `AccuracyDonut` |
| | `error_analysis.confusion_matrix` / `.most_common_error` | `ConfusionHeatmap` (outlined cell) + callout line |
| | `retriever_performance.best/worst/all_combinations` | `RetrieverPerformanceTable` + `RetrieverAccuracyChart` |
| | `recommendations[]` | `RecommendationsList` |

## Component design per enhancement (always-expanded)

1. **Retrieval pathway** (`RetrievalPathway.tsx`) — three-column layout (lexical / semantic / graph); each column headed by a `PathwayMiniBars` bar scaling its 0–1 score (accent fill on panel track), then rank, score, reason text; null rank/score renders "not retrieved" in muted text. Fusion gauge (thin stacked indicator up to `fusion_score`) + `fusion_explanation` below as a summary line.
2. **Chunk annotation** (`EvidenceItem.tsx`) — `annotated_html` rendered via `dangerouslySetInnerHTML` (safe: backend already HTML-escapes via `html.escape`, per `src/annotation/annotator.py`). `negation_analysis` badge (detected + keywords + scope), `component_matches` (three colored check/cross icons for S/V/O), and temporal badge ("current" green / "outdated · date" amber, hidden when null/unscoped/undated) shown inline under the marked-up text.
3. **Scoring transparency** (`ScoringBreakdown.tsx` + `ScoreContributionBars.tsx`) — every numeric key of `scoring_breakdown` (`baseline`, support/partial/refute components, `agreement_bonus`, `raw_score_value`, `final_score`, optional `evidence_counts`) rendered as a labeled signed bar: width normalized to max absolute value, green fill for positive contributions, red for negative; `final_score` emphasized. Non-numeric keys (`adjustment_reason`, `lm_judge_label`) render as muted text rows. Followed by `decision_thresholds` as three explanation lines (contradicted_rule / supported_rule / chosen_label).
4. **Rejected evidence** (`RejectedEvidenceList.tsx`) — always-expanded list under each verdict, same fields as accepted evidence but visually muted/struck-through to distinguish "considered but excluded"; includes `retrieval_score` as a tiny inline bar for scanability.
5. **Feedback loop** (`FeedbackCorrectionForm.tsx` + `FeedbackPage.tsx`) — a small inline form on every `VerdictCard` ("Correct this verdict": label dropdown + optional reason, posts `{feedback_id, actual_label, reason}` to `/feedback/correct`); on 404 (`verdict_not_found`) falls back to resending the full field set the verdict already has client-side. `FeedbackPage` calls `/feedback/analysis?days=N` (day-range selector) and renders: `AccuracyDonut` (Recharts radial gauge of `system_accuracy` with total-corrections stat chip), `ConfusionMatrix` (CSS-grid heatmap — diagonal shaded green by count intensity, off-diagonal red; hover title tooltips "predicted → actual: N"; the `most_common_error` cell outlined and echoed as a callout line), `RetrieverPerformanceTable` (table plus paired horizontal Recharts bars of accuracy vs error rate per combination, worst-first, best/worst badges), and `RecommendationsList`. Exact response keys are now known (`src/feedback/dashboard.py::compute_metrics` was read), so typed interfaces replace any generic fallback rendering.
6. **Caching / ops** — no dedicated cache endpoint exists. `ResultsSummary.tsx` shows `summary.cache_hits` from `/validate`. `HealthPage.tsx` shows `/health` output: overall status banner (green/amber/red), per-backend cards (healthy dot, `latency_ms` via `LatencyBars`, `error_message`, check timestamp), health `recommendations[]`, refresh button calling `/health?force=true` to bypass the server's 30 s TTL cache, and optional 30 s auto-refresh aligned to that TTL. Labeled "Backend Health", not cache stats.
7. **Multi-modal ingestion** — `chunk_types` histogram rendered as a real Recharts bar chart above the verdicts on `ValidatePage`; evidence items also tag their source chunk type via `metadata` if surfaced (no explicit chunk_type in `EvidenceOut` today, so this stays document-level).
8. **System configuration** (`HealthPage.tsx`, new) — one card surfacing every remaining field of `GET /config`: backend mode, SQLite path (muted), active embedding/SVO extractor model names, validator name, LM judge/classifier flags as enabled/disabled chips, per-retriever `backend_status` dots, and available-model lists shown as counts (expandable). This closes the last unintegrated endpoint surface.
9. **Temporal reasoning** — `temporal_status` and `chunk_timestamp` as a small badge on each `EvidenceItem` ("outdated · 1995-06-15" amber, "current" green, hidden entirely when null/unscoped/undated).
10. **Verdict distribution** (`ResultsSummary.tsx`) — beyond the numeric strip (total/supported/contradicted/partial/unknown/avg score/cache hits as StatChips), a `LabelDistributionChart` Recharts bar using the label palette (`--green/--red/--amber/--gray`) so the verdict mix is readable at a glance.

## Error handling

Port the existing pattern from `app.js`: the backend's error envelope is double-nested (`{"error": {"error": "...", "detail": "..."}}` per `api/errors.py`). `client.ts` normalizes this into a single `{message: string}` shape so components never deal with the nesting directly. `ErrorBanner.tsx` is a dismissible top banner, same UX as today. Charts fail soft: each chart component renders its own empty state ("No data") when its dataset is missing/empty rather than throwing.

## Build/dev workflow

```bash
cd frontend
npm install
npm run dev      # Vite dev server on 5173, proxies API calls to FastAPI on 8000
npm run build    # emits frontend/dist, consumed by FastAPI's StaticFiles mount
```

Routes are lazy-loaded (`React.lazy` + `Suspense`), so chart-heavy pages split into separate chunks automatically.

## Verification

1. `npm run build` succeeds with no TypeScript errors.
2. Start FastAPI (`uvicorn api.app:app`) pointed at `frontend/dist`; load `/` and confirm the built SPA serves.
3. Manual pass through `/validate`: submit a document + 2-3 triples covering each label and confirm every section renders — retrieval pathway (including a `null` retriever case → bars collapse to "not retrieved"), annotated HTML with negation, scoring contribution bars ending at `final_score`, rejected evidence with inline score bars, temporal badges (use a doc with a `Published:` date and an assertion `temporal_scope` to trigger outdated/future), label distribution + chunk-type histogram charts, and multi-modal chunk_types (ingest text containing a bullet list and an HTML table).
4. Submit a correction via the inline form, confirm `POST /feedback/correct` succeeds, then load `/feedback`: accuracy donut, confusion heatmap (correction visible, most-common-error outlined), retriever accuracy bars/table all reflect it.
5. Load `/health`: status banner, latency bars, recommendations render; click Refresh and confirm the timestamp changes even within the 30 s TTL window (proves `?force=true`); confirm the System Configuration card matches `GET /config`.
6. Confirm the dismissible error banner triggers correctly on a deliberately malformed request (e.g. empty `raw_text`).

## Future work (out of scope)

- `GET /feedback/timeline?days=N` endpoint + corrections-over-time area chart (requires the one additive backend route this plan intentionally avoids).
- Knowledge-graph visualization of the graph retriever's neighborhood (no node/edge payload exposed by `/validate` today).
