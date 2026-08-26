import { lazy, Suspense } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { LoadingSpinner } from "./components/shared";
import { DetailLevelProvider } from "./context/DetailLevelContext";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

const ValidatePage = lazy(() => import("./pages/ValidatePage"));
const FeedbackPage = lazy(() => import("./pages/FeedbackPage"));
const HealthPage = lazy(() => import("./pages/HealthPage"));
const OntologyPage = lazy(() => import("./pages/OntologyPage"));

export default function App() {
  return (
    <DetailLevelProvider>
      <header className="topbar">
        <h1>SVO Triple Verifier</h1>
        <nav className="nav">
          <NavLink to="/validate" className={({ isActive }) => (isActive ? "active" : "")}>
            Validate
          </NavLink>
          <NavLink to="/ontology" className={({ isActive }) => (isActive ? "active" : "")}>
            Ontology
          </NavLink>
          <NavLink to="/feedback" className={({ isActive }) => (isActive ? "active" : "")}>
            Feedback
          </NavLink>
          <NavLink to="/health" className={({ isActive }) => (isActive ? "active" : "")}>
            Backend Health
          </NavLink>
        </nav>
      </header>
      <main>
        <RouteErrorBoundary>
          <Suspense fallback={<LoadingSpinner message="Loading page…" />}>
            <Routes>
              <Route path="/" element={<Navigate to="/validate" replace />} />
              <Route path="/validate" element={<ValidatePage />} />
              <Route path="/ontology" element={<OntologyPage />} />
              <Route path="/feedback" element={<FeedbackPage />} />
              <Route path="/health" element={<HealthPage />} />
              <Route path="*" element={<Navigate to="/validate" replace />} />
            </Routes>
          </Suspense>
        </RouteErrorBoundary>
      </main>
    </DetailLevelProvider>
  );
}
