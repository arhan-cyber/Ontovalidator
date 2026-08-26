import { useCallback, useEffect, useState } from "react";

import { getConflicts, getOntologyGraph, validateOntology } from "../api/client";
import type {
  ConflictsResponse,
  OntologyGraphResponse,
  OntologyReport,
  Severity,
} from "../api/types";
import {
  ConflictQueue,
  ConformanceFindings,
  GroundingPanel,
  OntologyGraphView,
} from "../components/ontology";
import { Button, Card, ErrorBanner, LoadingSpinner, StatChip } from "../components/shared";

type Plane = "a" | "b" | "both";

function PlaneSummary({ report }: { report: OntologyReport }) {
  const { conformance, grounding } = report;
  return (
    <Card title={`Ontology ${report.ontology_version} vs meta-model ${report.metamodel_version}`}>
      {/* Two axes, never averaged: "conformant but contradicted by the manual"
          is the finding worth surfacing, and one blended score hides it. */}
      <div className="plane-grid">
        <div>
          <h4>
            Structural conformance{" "}
            <span className={conformance.passed ? "verdict-pass" : "verdict-fail"}>
              {conformance.passed ? "PASS" : "FAIL"}
            </span>
          </h4>
          <div className="stat-row">
            <StatChip label="errors" value={conformance.by_severity.error ?? 0} />
            <StatChip label="warnings" value={conformance.by_severity.warning ?? 0} />
            <StatChip label="info" value={conformance.by_severity.info ?? 0} />
          </div>
          <p className="muted small">Does the ontology obey its own meta-model?</p>
        </div>
        <div>
          <h4>
            Evidential grounding{" "}
            <span
              className={
                !grounding.ran ? "verdict-skip" : grounding.passed ? "verdict-pass" : "verdict-fail"
              }
            >
              {!grounding.ran ? "SKIPPED" : grounding.passed ? "PASS" : "FAIL"}
            </span>
          </h4>
          <div className="stat-row">
            <StatChip label="supported" value={grounding.by_label?.supported ?? 0} />
            <StatChip label="contradicted" value={grounding.by_label?.contradicted ?? 0} />
          </div>
          <p className="muted small">
            Do the source documents support its claims? Only contradiction fails — no evidence
            is a coverage gap, not a defect.
          </p>
        </div>
      </div>
    </Card>
  );
}

export default function OntologyPage() {
  const [plane, setPlane] = useState<Plane>("a");
  const [severity, setSeverity] = useState<Severity>("info");
  const [includeIt4it, setIncludeIt4it] = useState(false);

  const [report, setReport] = useState<OntologyReport | null>(null);
  const [graph, setGraph] = useState<OntologyGraphResponse | null>(null);
  const [conflicts, setConflicts] = useState<ConflictsResponse | null>(null);

  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadGraph = useCallback(async () => {
    try {
      setGraph(await getOntologyGraph());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const loadConflicts = useCallback(async () => {
    try {
      setConflicts(await getConflicts());
    } catch {
      // The registry can be disabled (503); that is a configuration choice,
      // not an error worth interrupting the page for.
      setConflicts(null);
    }
  }, []);

  useEffect(() => {
    void loadGraph();
    void loadConflicts();
  }, [loadGraph, loadConflicts]);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setReport(
        await validateOntology({
          plane,
          severity_threshold: severity,
          include_it4it: includeIt4it,
        }),
      );
      await loadConflicts();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <Card title="Run validation">
        <div className="filter-row">
          <label>
            Plane
            <select value={plane} onChange={(e) => setPlane(e.target.value as Plane)}>
              <option value="a">A — conformance only (fast)</option>
              <option value="b">B — grounding only</option>
              <option value="both">Both</option>
            </select>
          </label>
          <label>
            Min severity
            <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="error">error</option>
            </select>
          </label>
          {plane !== "a" && (
            <label className="checkbox" title="294 pages vs 24 for the process manuals">
              <input
                type="checkbox"
                checked={includeIt4it}
                onChange={(e) => setIncludeIt4it(e.target.checked)}
              />
              Include IT4IT standard
            </label>
          )}
          <Button onClick={run} disabled={running}>
            {running ? "Running…" : "Validate"}
          </Button>
        </div>
        {plane !== "a" && (
          <p className="muted small">
            Grounding ingests the document corpus and adjudicates every projected claim; it
            takes minutes, where conformance takes milliseconds.
          </p>
        )}
      </Card>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      {running && <LoadingSpinner message="Validating ontology…" />}

      {report && <PlaneSummary report={report} />}

      {conflicts && conflicts.conflicts.length > 0 && (
        <ConflictQueue
          conflicts={conflicts.conflicts}
          unreviewed={conflicts.unreviewed}
          onResolved={() => {
            void loadConflicts();
            void run();
          }}
        />
      )}

      {report && (
        <ConformanceFindings
          findings={report.conformance.findings}
          byRule={report.conformance.by_rule}
        />
      )}

      {report && <GroundingPanel grounding={report.grounding} />}

      {graph && <OntologyGraphView graph={graph} report={report} />}
    </div>
  );
}
