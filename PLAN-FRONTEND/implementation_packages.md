# Frontend Implementation: Subagent Work Packages

11 discrete, self-contained work packages for the React SPA rebuild. Each scoped to 1–2 hours, with clear entry/exit criteria and acceptance tests. Amendment v2: adds a dedicated visualization layer (Recharts + custom heatmap/bars), full `/config` and `/health` field coverage, and typed feedback-analysis interfaces.

---

## PACKAGE 1: Project Setup & Build Configuration

**Scope:** Initialize Vite + React + TypeScript project from scratch, configure all tooling.

**Deliverables:**
- `frontend/package.json` with React, React DOM, React Router DOM, **Recharts**, TypeScript, Vite, and dev dependencies
- `frontend/vite.config.ts` with React plugin, dev server proxy for `/validate`, `/config`, `/health`, `/feedback/*` → `http://localhost:8000`
- `frontend/tsconfig.json` with `jsx: react-jsx`, `target: ES2020`, `moduleResolution: bundler`
- `frontend/index.html` as Vite entry point with `<div id="root">` and `<script type="module" src="/src/main.tsx">`

**Entry Criteria:** Current directory: `/frontend/`; no prior npm/node files

**Dependencies:** None (foundation)

**Downstream:** All other packages

**Acceptance Tests:**
1. `npm install` completes with no errors (recharts resolves)
2. `npm run dev` starts Vite on port 5173 without errors
3. `npm run build` generates `frontend/dist/` with `index.html`, `assets/*.js`, `assets/*.css`
4. Navigating to `http://localhost:5173/` returns 200 and serves static HTML

**Notes:** Use minimal `src/main.tsx` that just renders `<div>Vite + React is working</div>` to verify build chain. Remove old static files (`index.html`, `app.js`) after confirming Vite works.

---

## PACKAGE 2: Type Layer & API Client

**Scope:** Create TypeScript interfaces mirroring backend schemas exactly, build fetch client wrapper with error normalization.

**Deliverables:**
- `frontend/src/api/types.ts`:
  - Core response types: `TripleIn`, `MatchedOut`, `EvidenceOut`, `RejectedEvidenceOut`, `VerdictOut`, `SummaryOut`, `BackendStatusOut`, `ValidateResponse`, `BackendHealthOut`, `HealthResponse`, `ConfigResponse`, `CorrectionRequest`, `CorrectionResponse`
  - Typed feedback-analysis payloads (exact keys confirmed from `src/feedback/dashboard.py::compute_metrics`):
    - `ConfusionMatrix = Record<string, Record<string, number>>`
    - `MostCommonError { predicted: string; actual: string; count: number }`
    - `FeedbackSummary { total_corrections: number; system_accuracy: number; window_days: number }`
    - `RetrieverCombinationStats { retrieval_sources: string[]; total_cases: number; accuracy: number; error_rate: number }`
    - `RetrieverPerformance { best_combination: RetrieverCombinationStats | null; worst_combination: ... | null; all_combinations: RetrieverCombinationStats[] }`
    - `FeedbackAnalysisResponse { summary: FeedbackSummary; error_analysis: { most_common_error: MostCommonError | null; confusion_matrix: ConfusionMatrix }; retriever_performance: RetrieverPerformance; recommendations: string[] }`
- `frontend/src/api/client.ts` with exported async functions:
  - `validate(req)` → POST /validate
  - `getConfig()` → GET /config
  - `getHealth(force = false)` → GET `/health?force=true` when force is set (bypasses server's 30 s TTL cache)
  - `submitCorrection(req)` → POST /feedback/correct
  - `getFeedbackAnalysis(days: number)` → GET /feedback/analysis?days=N
  - Error normalization: catch double-nested `{"error": {...}}`, return `{message: string}`, throw `ApiError` class

**Entry Criteria:** Package 1 complete; API running

**Dependencies:** Package 1 (TypeScript setup)

**Downstream:** All page packages (7, 8, 9)

**Acceptance Tests:**
1. TypeScript compilation succeeds
2. All Pydantic schema fields from `api/schemas.py` represented in `types.ts`
3. Calling `getConfig()` from browser console returns correct shape
4. Malformed validate request returns `ApiError` with readable `.message`
5. All exports are named (not default)

**Notes:** Simple `fetch()`, no external library. The generic key/value fallback renderer from v1 of this plan is no longer needed — dashboard shapes are fully typed.

---

## PACKAGE 3: Shared UI Components

**Scope:** Build reusable, composable UI blocks following existing dark palette.

**Deliverables:**
- `frontend/src/components/shared/Card.tsx` — wrapper div with `className="card"`, optional title/error/loading states
- `frontend/src/components/shared/Button.tsx` — variants: primary, secondary, danger, icon; optional disabled, loading, onClick, type
- `frontend/src/components/shared/LabelDot.tsx` — colored dot for label: `"supported" | "contradicted" | "partial" | "unknown"`
- `frontend/src/components/shared/ErrorBanner.tsx` — dismissible top banner; takes `message` and `onDismiss`
- `frontend/src/components/shared/LoadingSpinner.tsx` — text or animated spinner; optional `message`
- `frontend/src/components/shared/StatChip.tsx` — small label+value chip used by summary strips and dashboard stat rows

**Entry Criteria:** Packages 1–2 complete

**Dependencies:** Package 1 (React/TypeScript), Package 2 (API types, optional)

**Downstream:** All other packages

**Acceptance Tests:**
1. TypeScript compilation succeeds
2. Each component exports a named React.FC
3. Card renders `<div className="card">` with children
4. Button renders `<button>` with correct CSS classes per variant
5. LabelDot renders `<span className="label-{label}">` dot
6. StatChip renders `<span className="stat-chip">` with label/value slots
7. ErrorBanner renders only when message provided; dismiss calls onDismiss
8. All components accept and pass through standard HTML attributes

**Notes:** Use CSS variables from theme (Package 5). Keep unstyled; lean on theme.css.

---

## PACKAGE 4: Router & Layout Structure

**Scope:** Set up React Router with three main routes, shared layout shell, navigation, lazy-loaded route chunks.

**Deliverables:**
- `frontend/src/main.tsx` — ReactDOM.createRoot + `<BrowserRouter>` + `<App />`
- `frontend/src/App.tsx` — top-level shell with:
  - Header (title "SVO Triple Verifier", nav links/buttons)
  - `<Routes>` with `/validate` (default), `/feedback`, `/health`
  - Each page wrapped in `React.lazy(() => import(...))` + `<Suspense fallback={<LoadingSpinner />}>` so chart-heavy pages split into separate bundles
  - Fallback 404 route (redirect to `/validate`)
  - Global error boundary
- `frontend/src/pages/` directory structure (files stubbed; created as empty TSX)

**Entry Criteria:** Packages 1, 3 complete

**Dependencies:** Package 1 (React/Vite), Package 3 (shared components)

**Downstream:** Packages 7–9

**Acceptance Tests:**
1. TypeScript compilation succeeds
2. App starts without errors (`npm run dev`)
3. Clicking nav links changes URL and renders correct route
4. Navigating to `/nonexistent` redirects to `/validate`
5. Header visible across all pages
6. Network tab shows separate chunk per page on first visit

**Notes:** Use `react-router-dom` v6+.

---

## PACKAGE 5: Theme & Global Styles (incl. chart styles)

**Scope:** Port dark-theme CSS variables and global styles from existing `frontend/styles.css`; add visualization styles.

**Deliverables:**
- `frontend/src/theme.css`:
  - `:root` CSS variables (exact values from old `styles.css`): `--bg #0f1216`, `--panel #171b21`, `--border #2a2f37`, `--text #e6e9ef`, `--muted #9aa4b2`, `--accent #4f8cff`, `--green #38c172`, `--red #e3342f`, `--amber #f2a900`, `--gray #6b7280`
  - Global resets, `.topbar`, `main` (max-width 900px centered), `.card`, `.btn` variants, `.icon-btn`, `.loading`, `.error-banner`
  - Label-dot colors: `.label-supported/.label-contradicted/.label-partial/.label-unknown`
  - Existing classes: `.submit-row`, `.settings-grid`, `.triple-row`, `.triple-header`, `.summary`, `.verdict-card`, `.verdict-title`, `.score`, `.rationale`, `.evidence-item`
  - **New chart styles**: `.stat-chip`, `.bar-track`/`.bar-fill` (+ `.positive`/`.negative`), `.fusion-gauge`, `.heatmap-grid`/`.hm-cell` (+ intensity modifiers `.hm-diag-N` green scale / `.hm-off-N` red scale, `.hm-max` outline for most-common-error), `.latency-bar`, `.rejected-item` (muted + line-through)
  - Recharts overrides: dark tooltip background/border via a `.recharts-default-tooltip` override class
- Import theme.css in `main.tsx`

**Entry Criteria:** Packages 1, 4 complete; old `frontend/styles.css` available

**Dependencies:** Package 1 (CSS handling), Package 4 (App structure)

**Downstream:** All other packages

**Acceptance Tests:**
1. `npm run dev` applies dark theme
2. DevTools shows `:root` CSS variables defined and in use
3. All existing CSS class names present and correctly styled
4. Heatmap/bar/gauge classes render visibly on a scratch page
5. `npm run build` includes theme.css in output

**Notes:** Copy exact variable values from old `styles.css` to avoid color drift. No light-mode support needed.

---

## PACKAGE 6: Visualization Chart Components (NEW)

**Scope:** Build the shared dark-themed visualization layer consumed by all three pages. Recharts for bar/radial charts; custom div/CSS components for signed micro-bars, pathway bars, heatmap, and latency bars.

**Deliverables** (`frontend/src/components/charts/`):
- `chartTheme.ts` — palette constants mapped from CSS vars (`SUPPORTED: var(--green)` etc.), shared dark tooltip props (contentStyle/background/border), axis/text colors from `--muted`
- `LabelDistributionChart.tsx` — Recharts vertical BarChart; props `{ supported, contradicted, partial, unknown }`; each bar filled with its label color; tooltip shows counts
- `ChunkTypeHistogram.tsx` — Recharts horizontal BarChart; props `{ data: Record<string, number> }`; accent fill; empty state "No chunks"
- `AccuracyDonut.tsx` — Recharts RadialBarChart gauge; props `{ accuracy: number }` (0–1); percentage label center; green→amber→red fill by value bands (≥0.8 green, ≥0.5 amber, else red); empty state when no corrections
- `RetrieverAccuracyChart.tsx` — Recharts horizontal grouped BarChart; props `{ rows: RetrieverCombinationStats[] }`; two series: accuracy (`--green`) and error_rate (`--red`); combination labels as joined source names; sorted worst-first by caller
- `ConfusionHeatmap.tsx` — pure CSS grid; props `{ matrix: ConfusionMatrix; mostCommonError?: MostCommonError | null }`; fixed row/col order `[supported, contradicted, partial, unknown]`; cell background = count-intensity shade (diagonal green scale, off-diagonal red scale, alpha proportional to count/max); `title` tooltip "predicted → actual: N"; `mostCommonError` cell gets `.hm-max` outline; renders row/col headers and legend
- `ScoreContributionBars.tsx` — div-based signed bars; props `{ breakdown: Record<string, unknown> }`; numeric keys → row of [key, signed bar normalized to max |value|, value]; positive `--green`, negative `--red`; `final_score` row emphasized (bold + full-width marker); non-numeric values rendered as muted text lines
- `PathwayMiniBars.tsx` — div-based 0–1 scaled bar; props `{ score: number | null }`; null → muted "not retrieved"; used per retriever column; plus exported `FusionGauge` thin indicator scaling `fusion_score`
- `LatencyBars.tsx` — div-based bars; props `{ entries: Array<{ name: string; latency_ms: number | null }> }`; width relative to max latency; missing/null → muted dash

**Entry Criteria:** Packages 1–5 complete

**Dependencies:** Packages 1, 2 (types), 3 (shared), 5 (theme/chart styles)

**Downstream:** Packages 7, 8, 9

**Acceptance Tests:**
1. TypeScript compilation succeeds
2. Each chart exports a named component and renders its empty state when given empty/missing data (no crash)
3. LabelDistributionChart bars use correct label colors
4. ConfusionHeatmap shades diagonal green / off-diagonal red proportionally to counts; outlined cell matches provided mostCommonError
5. ScoreContributionBars handles negative values and non-numeric extras without crashing
6. Tooltips readable on dark background (no white-on-white)
7. A scratch route rendering every component passes visual smoke test

**Notes:** No state, no fetching — pure presentational props-in/components-out so they stay independently testable.

---

## PACKAGE 7: Validate Page (Main Workflow)

**Scope:** Build primary validation page with form, results display, all 8 enhancements rendered always-expanded, with visualizations.

**Deliverables:**
- `frontend/src/pages/ValidatePage.tsx` — orchestrates DocumentForm, ResultsSummary, VerdictCard; form submission/error/results state; calls `client.validate(req)`; ErrorBanner on API error, LoadingSpinner during validation; renders results only after success; ingestion info line (`ingestion_status`, `chunks_ingested`, `svos_extracted`) and backend status dots above the summary
- `frontend/src/components/validate/DocumentForm.tsx` — textarea for `raw_text`, TriplesEditor, settings section (embedding_model / svo_extractor selects populated from `/config` `available_*` lists, top_k number input), submit button; validation: ≥1 triple, non-empty raw_text
- `frontend/src/components/validate/TriplesEditor.tsx` — triple table (Subject, Relation, Object, action); add/remove rows; skips fully-empty rows, errors on partially-empty rows
- `frontend/src/components/validate/ResultsSummary.tsx` — StatChips row (total, supported, contradicted, partial, unknown, avg score 2dp, cache hits) + `LabelDistributionChart` + `ChunkTypeHistogram` side by side above verdicts
- `frontend/src/components/validate/VerdictCard.tsx` — LabelDot + triple + score title; rationale; evidence list (EvidenceItem); RejectedEvidenceList; ScoringBreakdown; RetrievalPathway per evidence; FeedbackCorrectionForm
- `frontend/src/components/validate/ScoringBreakdown.tsx` — wraps `ScoreContributionBars` for `scoring_breakdown`, then `decision_thresholds` as three explanation lines (contradicted_rule / supported_rule / chosen_label)
- `frontend/src/components/validate/RejectedEvidenceList.tsx` — always-expanded; each `RejectedEvidenceOut` muted/struck-through with chunk_id, inline bar for retrieval_score, adjudication, reason_rejected
- `frontend/src/components/validate/EvidenceItem.tsx` — annotated HTML via `dangerouslySetInnerHTML`; negation badge (detected + keywords + scope); S/V/O component-match check/cross icons; temporal badge ("current" green, "outdated · date" amber, hidden if null/unscoped/undated); chunk metadata (chunk_id, source, confidence, match_type)
- `frontend/src/components/validate/RetrievalPathway.tsx` — three columns (Lexical/Semantic/Graph); each: `PathwayMiniBars` score bar, rank, score, reason ("not retrieved" when null); `FusionGauge` + fusion_explanation below
- `frontend/src/components/validate/FeedbackCorrectionForm.tsx` — collapsible "Correct this verdict"; label dropdown, optional reason; POST `/feedback/correct` `{feedback_id, actual_label, reason}`; "Correction recorded" on success; on 404 falls back to resending full verdict fields

**Entry Criteria:** Packages 1–6 complete; API `/validate` working

**Dependencies:** Packages 1–6

**Downstream:** None (leaf feature)

**Acceptance Tests:**
1. Page loads with DocumentForm, triples table, settings, submit button
2. Add/remove triple rows work; empty raw_text shows error
3. Submit calls `/validate`, renders ResultsSummary + VerdictCards
4. ResultsSummary shows stat chips, label chart, and chunk-type histogram
5. Each VerdictCard shows title/score/rationale/evidence/rejected/scoring bars/temporal badges/pathway bars/negation/component matches
6. ScoreContributionBars ends at final_score and matches verdict.score
7. Pathway null case collapses to "not retrieved"
8. FeedbackCorrectionForm POSTs successfully on submit
9. No TypeScript errors

**Notes:** Most complex page; break into focused files. React state only, no Redux.

---

## PACKAGE 8: Feedback Page (Dashboard & Analysis)

**Scope:** Chart-driven dashboard for feedback analysis over a selectable day window.

**Deliverables:**
- `frontend/src/pages/FeedbackPage.tsx` — loads `/feedback/analysis?days=N` on mount; day-range selector (7/14/30/90, default 30) re-fetching on change; ErrorBanner on failure (e.g., 503 feedback_disabled); LoadingSpinner while fetching; renders AccuracyDonut + corrections StatChip, ConfusionMatrix, RetrieverPerformanceTable, RecommendationsList
- `frontend/src/components/feedback/ConfusionMatrix.tsx` — legend + most-common-error callout line ("Most common error: predicted → actual (N)") + wraps `ConfusionHeatmap`
- `frontend/src/components/feedback/RetrieverPerformanceTable.tsx` — table (Combination, Total, Accuracy %, Error Rate %) worst-first, best/worst badges, paired `RetrieverAccuracyChart` beside/below it
- `frontend/src/components/feedback/RecommendationsList.tsx` — card list with icons; empty state "No recommendations at this time"

**Entry Criteria:** Packages 1–6 complete; `/feedback/analysis` endpoint working

**Dependencies:** Packages 1–6

**Downstream:** None (leaf feature)

**Acceptance Tests:**
1. Page loads with day selector (default 30) and spinner
2. On response: donut shows system_accuracy band color; corrections chip matches total_corrections
3. Heatmap grid displays predicted/actual labels with counts and intensity shading; correction submitted via Validate page appears here after refresh
4. most_common_error cell outlined and echoed in callout
5. Retriever table lists all combinations sorted worst-first; chart bars match table numbers; best/worst badges correct
6. Changing day selector triggers new API call and re-render
7. 503 → ErrorBanner with readable message
8. All components render defensively (no crash on empty matrix)

**Notes:** Exact keys are typed in Package 2 — no generic fallback renderer needed.

---

## PACKAGE 9: Health & System Page (full `/health` + `/config` integration)

**Scope:** Operational page combining backend health status, latency visualization, health recommendations, and a complete system-configuration view.

**Deliverables:**
- `frontend/src/pages/HealthPage.tsx`:
  - Loads `/health` on mount; also loads `/config` once for the System Configuration card
  - Overall status banner: "Healthy" green / "Degraded" amber / "Unhealthy" red, with check timestamp
  - Per-backend cards from `backends{}` (rendered generically over keys so future backends appear automatically): healthy/unhealthy dot via LabelDot convention, `latency_ms` visualized with `LatencyBars`, `error_message` in red when present, per-backend check timestamp
  - Health `recommendations[]` list below the cards
  - Refresh button → `getHealth(true)` (`/health?force=true`, bypasses server TTL); optional auto-refresh every 30 s aligned to server TTL_SECONDS
  - **System Configuration card** (from `/config`): backend_mode, sqlite_path (muted), embedding_model_name + svo_extractor_name + validator_name, enable_lm_judge / enable_lm_classifier as enabled/disabled chips, backend_status dots for lexical/semantic/graph, available_embedding_models / available_svo_extractors as counts with expandable lists

**Entry Criteria:** Packages 1–6 complete; `/health` and `/config` working

**Dependencies:** Packages 1–6

**Downstream:** None (leaf feature)

**Acceptance Tests:**
1. Page loads with spinner, then banner + backend cards render
2. Banner color matches overall_status; timestamp displayed
3. Each backend shows dot, latency bar scaled to max, error_message when unhealthy
4. Recommendations list renders all strings; empty state handled
5. Refresh triggers new call with `?force=true`; response timestamp changes even within 30 s of previous fetch
6. Auto-refresh (if enabled) fires every 30 s
7. Config card matches every field returned by GET /config; neo4j password never expected client-side
8. Error states show ErrorBanner for both endpoints independently

**Notes:** Two data sources, one page — keep the config card visually separate (own Card) from live health.

---

## PACKAGE 10: Backend Mount Point Update

**Scope:** Update FastAPI to serve Vite-built SPA instead of static frontend folder.

**Deliverables:**
- Edit `api/app.py`, line 23:
  - Change: `FRONTEND_DIR = Path(__file__).parent.parent / "frontend"`
  - To: `FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"`
- Verify `if FRONTEND_DIR.exists()` check still passes

**Entry Criteria:** Packages 1–9 complete and tested locally; `npm run build` generates `frontend/dist/`

**Dependencies:** Packages 1–9 (SPA must be built first)

**Downstream:** None (final integration)

**Acceptance Tests:**
1. FastAPI starts without errors
2. `http://localhost:8000/` serves SPA's `index.html` from dist/
3. SPA fully functional (validate, feedback, health pages work through same origin)
4. Refresh on `/feedback` and `/health` returns SPA's `index.html` (client-side routing)
5. API endpoints still respond correctly

**Notes:** One-line code change. Confirm `frontend/dist/` exists before deploying. Delete old `frontend/` static files after verified.

---

## PACKAGE 11: Build, Integration & Verification

**Scope:** Execute full build pipeline, integrate SPA with FastAPI, run manual verification checklist covering all enhancements and all charts/endpoints.

**Deliverables:**
- Confirm Packages 1–10 complete (TypeScript checks pass)
- `cd frontend && npm run build` → clean `dist/`
- Start FastAPI: `uvicorn api.app:app --reload`
- Manual verification checklist:
  1. Submit document + triples hitting each label; verify stat chips, label distribution chart, chunk-type histogram
  2. Verify per-verdict rendering: pathway bars (incl. null case), annotated HTML + negation, scoring contribution bars ending at final_score, rejected evidence with inline score bars, temporal badges (Published date + temporal_scope doc), component-match icons
  3. Submit correction via inline form; verify POST succeeds and "Correction recorded" appears
  4. Load `/feedback`: donut band color matches system_accuracy; heatmap reflects the correction; most-common-error cell outlined; retriever bars match table values
  5. Change day selector; confirm refetch and re-render
  6. Load `/health`: banner, latency bars, recommendations; force-refresh changes timestamp within TTL window; System Configuration card matches GET /config exactly
  7. Trigger error banner (empty raw_text) and verify dismiss behavior
  8. Confirm lazy-loaded chunks load on first navigation to /feedback and /health

**Entry Criteria:** Packages 1–10 complete; FastAPI running on 8000; test document data ready

**Dependencies:** All prior packages

**Downstream:** None (final verification)

**Acceptance Tests:**
1. `npm run build` succeeds, no TypeScript errors; `dist/` contains index.html + assets
2. FastAPI serves `/` → 200 SPA HTML
3. Every chart renders real data with correct empty state when data absent
4. Chart tooltips readable on dark theme
5. All endpoint fields from the integration map visible somewhere in the UI
6. Correction round-trip works end to end (form → analysis dashboard)
7. No console errors during a full pass through all three pages

**Notes:** If any check fails, trace back to the owning package. Document divergences from plan.

---

## Critical Files for Implementation

1. `frontend/package.json` — dependencies incl. recharts, scripts, configuration
2. `frontend/src/api/client.ts` — fetch wrappers (5 endpoints, force-refresh support, error normalization)
3. `frontend/src/api/types.ts` — exact interfaces for every response incl. typed feedback-analysis payloads
4. `frontend/src/components/charts/` — shared visualization layer consumed by all pages
5. `frontend/src/pages/ValidatePage.tsx` — main validation workflow (largest, most complex)
6. `frontend/src/components/validate/VerdictCard.tsx` — single verdict display (orchestrates 8 enhancements)
7. `api/app.py` — FastAPI mount point (single line change to FRONTEND_DIR)
