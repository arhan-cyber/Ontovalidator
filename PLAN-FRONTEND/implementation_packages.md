# Frontend Implementation: Subagent Work Packages

10 discrete, self-contained work packages for the React SPA rebuild. Each scoped to 1–2 hours, with clear entry/exit criteria and acceptance tests.

---

## PACKAGE 1: Project Setup & Build Configuration

**Scope:** Initialize Vite + React + TypeScript project from scratch, configure all tooling.

**Deliverables:**
- `frontend/package.json` with React, React DOM, React Router DOM, TypeScript, Vite, and dev dependencies
- `frontend/vite.config.ts` with React plugin, dev server proxy for `/validate`, `/config`, `/health`, `/feedback/*` → `http://localhost:8000`
- `frontend/tsconfig.json` with `jsx: react-jsx`, `target: ES2020`, `moduleResolution: bundler`
- `frontend/index.html` as Vite entry point with `<div id="root">` and `<script type="module" src="/src/main.tsx">`

**Entry Criteria:** Current directory: `/frontend/`; no prior npm/node files

**Dependencies:** None (foundation)

**Downstream:** All other packages

**Acceptance Tests:**
1. `npm install` completes with no errors
2. `npm run dev` starts Vite on port 5173 without errors
3. `npm run build` generates `frontend/dist/` with `index.html`, `assets/*.js`, `assets/*.css`
4. Navigating to `http://localhost:5173/` returns 200 and serves static HTML

**Notes:** Use minimal `src/main.tsx` that just renders `<div>Vite + React is working</div>` to verify build chain. Remove old static files (`index.html`, `app.js`) after confirming Vite works.

---

## PACKAGE 2: Type Layer & API Client

**Scope:** Create TypeScript interfaces mirroring backend schemas, build fetch client wrapper with error normalization.

**Deliverables:**
- `frontend/src/api/types.ts` with interfaces:
  - `TripleIn`, `MatchedOut`, `EvidenceOut`, `RejectedEvidenceOut`, `VerdictOut`, `SummaryOut`, `BackendStatusOut`, `ValidateResponse`
  - `CorrectionRequest`, `CorrectionResponse`
  - `FeedbackAnalysisResponse` (with `summary`, `error_analysis`, `retriever_performance`, `recommendations` as `Dict[string, unknown>`)
  - `BackendHealthOut`, `HealthResponse`, `ConfigResponse`
- `frontend/src/api/client.ts` with exported async functions:
  - `validate(req: ValidateRequest): Promise<ValidateResponse>` (POST /validate)
  - `getConfig(): Promise<ConfigResponse>` (GET /config)
  - `getHealth(): Promise<HealthResponse>` (GET /health)
  - `submitCorrection(req: CorrectionRequest): Promise<CorrectionResponse>` (POST /feedback/correct)
  - `getFeedbackAnalysis(days: number): Promise<FeedbackAnalysisResponse>` (GET /feedback/analysis?days=N)
  - Error normalization: catch double-nested `{"error": {"error": "...", "detail": "..."}}`, return `{message: string}`, throw `ApiError` class

**Entry Criteria:** Package 1 complete; API running

**Dependencies:** Package 1 (TypeScript setup)

**Downstream:** Packages 3, 6, 7, 8

**Acceptance Tests:**
1. TypeScript compilation succeeds
2. All Pydantic schema fields from `api/schemas.py` represented in `types.ts`
3. Calling `getConfig()` from browser console returns correct shape
4. Malformed validate request returns `ApiError` with readable `.message`
5. All exports are named (not default)

**Notes:** Use simple `fetch()` with no external library. Create integration test file `src/api/__test__/client.test.ts` (no network calls, just type/export validation). `FeedbackAnalysisResponse` fields intentionally typed as `Dict[string, unknown>` — Package 7 will read `dashboard.py::compute_metrics` and adapt.

---

## PACKAGE 3: Shared UI Components

**Scope:** Build reusable, composable UI blocks following existing dark palette.

**Deliverables:**
- `frontend/src/components/shared/Card.tsx` — wrapper div with `className="card"`, optional title/error/loading states
- `frontend/src/components/shared/Button.tsx` — button with variants: primary, secondary, danger, icon; optional disabled, loading, onClick, type
- `frontend/src/components/shared/LabelDot.tsx` — colored dot for label: takes `label: "supported" | "contradicted" | "partial" | "unknown"`
- `frontend/src/components/shared/ErrorBanner.tsx` — dismissible top banner; takes `message: string` and `onDismiss: () => void`
- `frontend/src/components/shared/LoadingSpinner.tsx` — text or animated spinner; takes optional `message: string`

**Entry Criteria:** Packages 1–2 complete

**Dependencies:** Package 1 (React/TypeScript), Package 2 (API types, optional)

**Downstream:** All other packages

**Acceptance Tests:**
1. TypeScript compilation succeeds
2. Each component exports a named React.FC
3. Card renders `<div className="card">` with children
4. Button renders `<button>` with correct CSS classes per variant
5. LabelDot renders `<span className="label-{label}">` dot
6. ErrorBanner renders only when message provided; dismiss calls onDismiss
7. LoadingSpinner renders text + optional spinner
8. All components accept and pass through standard HTML attributes

**Notes:** Use CSS variables from theme (Package 5): `--bg`, `--panel`, `--border`, `--text`, `--muted`, `--accent`, `--green`, `--red`, `--amber`, `--gray`. Keep unstyled; lean on theme.css. Pass `className` and `style` as spread props for reusability.

---

## PACKAGE 4: Router & Layout Structure

**Scope:** Set up React Router with three main routes, shared layout shell, navigation.

**Deliverables:**
- `frontend/src/main.tsx` — ReactDOM.createRoot + `<BrowserRouter>` + `<App />`
- `frontend/src/App.tsx` — top-level shell with:
  - Header (title "SVO Triple Verifier", nav links/buttons)
  - `<Routes>` with `/validate`, `/feedback`, `/health`
  - Fallback 404 route (redirect to `/validate` or show message)
  - Global error boundary (catches render errors, displays ErrorBanner)
- `frontend/src/pages/` directory structure (files stubbed; created as empty TSX)

**Entry Criteria:** Packages 1, 3 complete

**Dependencies:** Package 1 (React/Vite), Package 3 (shared components)

**Downstream:** Packages 6–8

**Acceptance Tests:**
1. TypeScript compilation succeeds
2. App starts without errors (`npm run dev`)
3. Clicking nav links changes URL and renders correct route
4. Navigating to `/nonexistent` redirects or shows 404
5. Header visible across all pages

**Notes:** Use `react-router-dom` v6+ with `createBrowserRouter` or `BrowserRouter + Routes`. Global error boundary can be class component with `componentDidCatch` or error boundary library. Header includes nav to all three pages.

---

## PACKAGE 5: Theme & Global Styles

**Scope:** Port dark-theme CSS variables and global styles from existing `frontend/styles.css`.

**Deliverables:**
- `frontend/src/theme.css` with:
  - `:root` CSS variable definitions (from existing `styles.css`): `--bg`, `--panel`, `--border`, `--text`, `--muted`, `--accent`, `--green`, `--red`, `--amber`, `--gray`
  - Global resets: `* { box-sizing: border-box; }`, `body { margin: 0; font-family: ...; background: var(--bg); color: var(--text); }`
  - `.topbar` (header), `main` (max-width 900px, centered, padding)
  - `.card`, `.btn` (primary/secondary/danger), `.icon-btn`, `.loading`, `.error-banner`
  - Label-dot colors: `.label-supported`, `.label-contradicted`, `.label-partial`, `.label-unknown`
  - `.submit-row`, `.settings-grid`, `.triple-row`, `.triple-header`, `.summary`, `.verdict-card`, `.verdict-title`, `.score`, `.rationale`, `.evidence-item`
- `frontend/src/index.css` or import theme.css in `main.tsx`

**Entry Criteria:** Packages 1, 4 complete; old `frontend/styles.css` available

**Dependencies:** Package 1 (CSS handling), Package 4 (App structure)

**Downstream:** All other packages

**Acceptance Tests:**
1. `npm run dev` applies dark theme (dark bg, light text, colored accents)
2. DevTools shows `:root` CSS variables defined and in use
3. All existing CSS class names present and correctly styled
4. `npm run build` includes theme.css in output

**Notes:** Copy exact variable values from old `styles.css` to avoid color drift. Delete old `styles.css` after confirming theme.css works. No light-mode support needed (plan specifies dark only).

---

## PACKAGE 6: Validate Page (Main Workflow)

**Scope:** Build primary validation page with form, results display, all 8 enhancements rendered always-expanded.

**Deliverables:**
- `frontend/src/pages/ValidatePage.tsx` — orchestrates:
  - DocumentForm, ResultsSummary, VerdictCard components
  - Form submission state, error state, results
  - Calls `client.validate(req)` on submit
  - ErrorBanner on API error, LoadingSpinner during validation
  - Renders results only after success
  - Chunk_types histogram above verdicts

- `frontend/src/components/validate/DocumentForm.tsx` — form with:
  - Textarea for `raw_text`
  - TriplesEditor component
  - Settings section: embedding_model, svo_extractor, top_k (from `/config`)
  - Submit button
  - Validation: at least one triple, non-empty raw_text
  - Calls `onSubmit(req: ValidateRequest)`

- `frontend/src/components/validate/TriplesEditor.tsx` — triple table:
  - Table header: Subject, Relation, Object, (action column)
  - One triple-row per triple (start with 1 empty row)
  - Add Row button, Remove Row button (delete if multiple, clear if only one)
  - Skips fully-empty rows, errors on partially-empty rows

- `frontend/src/components/validate/ResultsSummary.tsx` — summary strip:
  - Total, Supported, Contradicted, Partial, Unknown (from `summary`)
  - Avg score (2 decimals), Cache hits (from `summary.cache_hits`)
  - Chunk types histogram (e.g., "text: 12, table_row: 3")

- `frontend/src/components/validate/VerdictCard.tsx` — one verdict (always-expanded):
  - Title: LabelDot + triple (S–R–O) + score
  - Rationale
  - Evidence list (calls EvidenceItem)
  - Rejected evidence list (calls RejectedEvidenceList)
  - Scoring breakdown (calls ScoringBreakdown)
  - Feedback correction form (calls FeedbackCorrectionForm)

- `frontend/src/components/validate/ScoringBreakdown.tsx` — scoring transparency:
  - Each key in `scoring_breakdown` as labeled row (baseline, support/partial/refute components, agreement_bonus, raw_score, final_score, adjustment_reason/lm_judge_label)
  - `decision_thresholds` below as explanation (contradicted rule / supported rule / chosen label)

- `frontend/src/components/validate/RejectedEvidenceList.tsx` — always-expanded section:
  - Each RejectedEvidenceOut with muted/struck-through styling
  - chunk_id, retrieval_score, adjudication, reason_rejected

- `frontend/src/components/validate/EvidenceItem.tsx` — one evidence span:
  - Annotated HTML (via `dangerouslySetInnerHTML`, safe per plan)
  - Negation analysis badge (if present): negation_detected, keywords, scope
  - Component matches: S/V/O colored icons (if present)
  - Temporal status badge (if present): "current" (green), "outdated · date" (amber), hidden if null/unscoped/undated
  - Chunk metadata: chunk_id, source, confidence, match_type

- `frontend/src/components/validate/RetrievalPathway.tsx` — per-retriever info:
  - Three-column layout: Lexical, Semantic, Graph
  - Each shows: rank, score, reason (or "not retrieved" if null)
  - Fusion score + explanation below
  - Muted/smaller font

- `frontend/src/components/validate/FeedbackCorrectionForm.tsx` — inline feedback UI:
  - Collapsible form ("Correct this verdict")
  - Label dropdown (supported/contradicted/partial/unknown)
  - Optional reason text area
  - Submit button
  - POST to `/feedback/correct` with `{feedback_id, actual_label, reason}`
  - Show "Correction recorded" on success
  - On 404: fall back to accepting full verdict fields

**Entry Criteria:** Packages 1–5 complete; API `/validate` working

**Dependencies:** Packages 1–5

**Downstream:** None (leaf feature)

**Acceptance Tests:**
1. Page loads, displays DocumentForm, triples table, settings, submit button
2. Add/remove triple rows work
3. Empty raw_text shows error
4. Submit with triple + text calls `/validate`, renders ResultsSummary + VerdictCards
5. Each VerdictCard shows: title, score, rationale, evidence list, rejected evidence (if any), scoring breakdown, temporal badges (if present), retrieval pathway, negation analysis, component matches
6. FeedbackCorrectionForm: click opens form, submit POSTs to `/feedback/correct`
7. Chunk types histogram renders above verdicts
8. Temporal badges: "current" (green), "outdated · date" (amber), hidden if null
9. No TypeScript errors

**Notes:** Most complex page; break into focused files. Form state in DocumentForm/ValidatePage (React state, no Redux). Each component independently testable. Negation/component_matches/temporal_status optional; render if present. FeedbackCorrectionForm is small; POST on submit, refresh status flag in parent.

---

## PACKAGE 7: Feedback Page (Dashboard & Analysis)

**Scope:** Build dashboard for feedback analysis (confusion matrix, retriever performance, recommendations).

**Deliverables:**
- `frontend/src/pages/FeedbackPage.tsx` — page component:
  - Loads `/feedback/analysis?days=N` on mount
  - Day range selector (default 30)
  - ErrorBanner if `/feedback/analysis` fails (e.g., 503)
  - LoadingSpinner while fetching
  - Renders ConfusionMatrix, RetrieverPerformanceTable, RecommendationsList

- `frontend/src/components/feedback/ConfusionMatrix.tsx` — confusion matrix visualization:
  - Rows: predicted label; Columns: actual label; Cells: count
  - Diagonal (correct) in green, off-diagonal in red/warning
  - Empty: show "No corrections recorded yet"

- `frontend/src/components/feedback/RetrieverPerformanceTable.tsx` — retriever accuracy table:
  - Columns: Retriever Combination, Total Cases, Accuracy, Error Rate
  - Rows: sorted by error rate (worst first)
  - Highlight best/worst combos if available
  - Empty: show "No retriever data"

- `frontend/src/components/feedback/RecommendationsList.tsx` — actionable recommendations:
  - Each recommendation as card/list item with icon
  - Empty: show "No recommendations at this time"

**Entry Criteria:** Packages 1–5 complete; Package 2 complete; `/feedback/analysis` endpoint working

**Dependencies:** Packages 1–5, Package 2

**Downstream:** None (leaf feature)

**Acceptance Tests:**
1. Page loads, shows day selector (default 30) and loading spinner
2. After `/feedback/analysis?days=30` returns, spinner disappears, three components render
3. ConfusionMatrix displays grid with predicted/actual labels and counts
4. RetrieverPerformanceTable shows all combinations with accuracy/error rates
5. RecommendationsList shows all recommendation strings
6. Changing day selector triggers new API call and re-renders
7. If `/feedback/analysis` fails with 503, ErrorBanner shows message
8. All fields render defensively (no crashes on unexpected shapes)

**Notes:** **Before finalizing**, read `src/feedback/dashboard.py::compute_metrics()` (lines 18–38) to understand exact keys:
- `summary`: `total_corrections`, `system_accuracy`, `window_days`
- `error_analysis`: `most_common_error`, `confusion_matrix`
- `retriever_performance`: `best_combination`, `worst_combination`, `all_combinations` (each: `retrieval_sources`, `total_cases`, `accuracy`, `error_rate`)
- `recommendations`: list of strings

Use generic fallback renderer for unexpected nested objects. Handle label with no errors (show 0s or hide row).

---

## PACKAGE 8: Health Page (Backend Status)

**Scope:** Display backend health status and operational metrics.

**Deliverables:**
- `frontend/src/pages/HealthPage.tsx` — page component:
  - Loads `/health` endpoint on mount
  - LoadingSpinner while fetching
  - ErrorBanner if `/health` fails
  - Renders backend status for each retriever (lexical, semantic, graph)
  - Shows overall_status (healthy/degraded/unhealthy)
  - Displays timestamp of last health check
  - Optional: refresh button for manual re-check
  - Optional: auto-refresh every 30 seconds

**Entry Criteria:** Packages 1–5 complete; Package 2 complete; `/health` endpoint working

**Dependencies:** Packages 1–5, Package 2

**Downstream:** None (leaf feature)

**Acceptance Tests:**
1. Page loads, shows loading spinner
2. After `/health` returns, spinner disappears, status renders
3. Overall status displayed (green "Healthy", amber "Degraded", red "Unhealthy")
4. Each backend shown with status, latency_ms, error_message
5. Timestamp of health check displayed
6. Refresh button triggers new `/health` call (optional)
7. Auto-refresh works (optional)

**Notes:** Label as "Backend Health", not "Cache Status". Simplest page; keep minimal. Use Card component for each backend status block.

---

## PACKAGE 9: Backend Mount Point Update

**Scope:** Update FastAPI to serve Vite-built SPA instead of static frontend folder.

**Deliverables:**
- Edit `api/app.py`, line 23:
  - Change: `FRONTEND_DIR = Path(__file__).parent.parent / "frontend"`
  - To: `FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"`
- Verify `if FRONTEND_DIR.exists()` check still passes

**Entry Criteria:** Packages 1–8 complete and tested locally; `npm run build` succeeds and generates `frontend/dist/`

**Dependencies:** Packages 1–8 (SPA must be built first)

**Downstream:** None (final integration)

**Acceptance Tests:**
1. FastAPI starts without errors
2. Navigating to `http://localhost:8000/` serves SPA's `index.html` from dist/
3. SPA loads and fully functional (validate, feedback, health pages work)
4. Refresh on `/feedback` and `/health` returns SPA's `index.html` (client-side routing)
5. API endpoints (`/validate`, `/config`, `/health`, `/feedback/*`) still respond correctly

**Notes:** One-line code change. Confirm `frontend/dist/` exists before deploying; if missing, app fails to mount. Delete old `frontend/` static files (old `index.html`, `app.js`, `styles.css`) after verified.

---

## PACKAGE 10: Build, Integration & Verification

**Scope:** Execute full build pipeline, integrate SPA with FastAPI, run manual verification checklist for all 8 enhancements.

**Deliverables:**
- Confirm all prior packages complete (run TypeScript checks, linting if configured)
- Run `cd frontend && npm run build`, verify `dist/` generated cleanly
- Update `api/app.py` (Package 9) to serve `frontend/dist/`
- Start FastAPI: `uvicorn api.app:app --reload`
- Run manual pass checklist:
  1. Submit document + 2–3 triples (supported/contradicted/partial/unknown labels)
  2. Verify every section renders:
     - Retrieval pathway (including null case → "not retrieved")
     - Annotated HTML with negation analysis
     - Scoring breakdown with decision thresholds
     - Rejected evidence (muted/struck-through styling)
     - Temporal badges (test with Published date + assertion temporal_scope)
     - Multi-modal chunk_types (doc with bullet list + HTML table)
  3. Submit correction via inline form; verify POST `/feedback/correct` succeeds
  4. Load `/feedback`, confirm confusion matrix reflects correction
  5. Load `/health`, confirm backend statuses render
  6. Trigger error banner (empty raw_text), verify dismissible behavior

**Entry Criteria:** Packages 1–9 complete; FastAPI running on 8000; test document data ready

**Dependencies:** Packages 1–9 (everything)

**Downstream:** None (final verification)

**Acceptance Tests:**
1. `npm run build` in `frontend/` succeeds, no TypeScript errors
2. `dist/` exists with `index.html`, `assets/*.js`, `assets/*.css`
3. FastAPI serves `/` → 200, returns SPA HTML
4. `/validate` form submits, API succeeds, results render with all enhancements
5. Retrieval pathway shows three columns (lexical/semantic/graph) with ranks/scores/reasons
6. Annotated HTML renders safely (no script injection, HTML entities escaped)
7. Negation badge shows if `negation_detected` true; keywords and scope visible
8. Scoring breakdown shows all keys from `scoring_breakdown` dict
9. Rejected evidence renders with visual distinction (muted/struck-through)
10. Temporal badges: green "current", amber "outdated", hidden if null
11. Component matches render as S/V/O icons (green checks, red crosses)
12. Chunk types histogram renders above verdicts
13. Correction form submits via POST, shows "Correction recorded"
14. `/feedback` page loads, confusion matrix reflects correction
15. `/health` page displays backend statuses
16. Error banner appears on malformed requests, dismisses on click

**Notes:** Final integration and QA. If any enhancement fails, trace back to relevant package and debug. Document divergences from plan. Once all 10 checks pass, React SPA is production-ready.

---

## Critical Files for Implementation

1. `frontend/package.json` — Project dependencies, scripts, configuration
2. `frontend/src/api/client.ts` — API client wrapper (fetch + error normalization)
3. `frontend/src/pages/ValidatePage.tsx` — Main validation workflow (largest, most complex)
4. `frontend/src/components/validate/VerdictCard.tsx` — Single verdict display (orchestrates 8 enhancements)
5. `api/app.py` — FastAPI mount point (single line change to `FRONTEND_DIR`)
