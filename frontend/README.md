# SVO Triple Verifier — Frontend

React + TypeScript SPA (Vite) for the Ontovalidator pipeline: submit a document and triples, see verdicts with as much or as little pipeline internals as you want.

## Setup

```bash
npm install
```

## Development

```bash
npm run dev
```

Starts the Vite dev server on `http://localhost:5173`. Requests to `/api/*` are proxied to `http://localhost:8000` (see `vite.config.ts`) — run the backend with `uvicorn api.app:app` (default port 8000) alongside this.

## Build

```bash
npm run build
```

Runs `tsc` (type-check) then `vite build`, producing `dist/`. This is **not** committed to git (see root `.gitignore`) — build it fresh before deploying. `api/app.py` mounts `dist/` directly via `StaticFiles` and serves `index.html` for any non-`/api` route, so once built, `GET /` on the running FastAPI server serves the full SPA with no separate frontend server needed.

## How it talks to the backend

- Dev mode: Vite's proxy (`vite.config.ts`) forwards `/api/*` to the backend.
- Built/production mode: the backend serves the built SPA directly, and the SPA's own `fetch` calls to `/api/*` resolve against the same origin — no proxy needed since there's only one server.
- API client: `src/api/client.ts` (typed request/response wrappers) and `src/api/types.ts` (types mirroring `api/schemas.py` — keep these in sync if the backend response shape changes).

## Trace detail toggle

`src/context/DetailLevelContext.tsx` / `src/components/shared/DetailLevelToggle.tsx` control how much of each verdict is rendered, independent of the API response (the backend always returns the full payload — this is purely presentational):

| Level | Shows |
|---|---|
| Verdict | Label, score, one-line rationale only |
| Summary *(default)* | + evidence text, rule hits, negation/temporal badges |
| Detailed | + retrieval pathway (fusion gauge, per-retriever rank/score), scoring breakdown, rejected evidence |
| Full trace | + per-retriever reasoning text, annotated-HTML highlighting, chunk IDs, a raw verdict-JSON panel |

The choice persists to `localStorage` (`svo:detailLevel`) so it survives a reload. The toggle lives above the document form on the Validate page and is settable at any time.

## Pages

- **Validate** (`/validate`) — submit a document + triples, view verdicts.
- **Feedback** (`/feedback`) — correction history and retriever performance analysis.
- **Health** (`/health`) — backend health status per retrieval/storage backend.
