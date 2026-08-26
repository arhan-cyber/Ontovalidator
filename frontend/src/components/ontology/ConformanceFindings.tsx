import { useMemo, useState } from "react";

import type { ConformanceFinding, Severity } from "../../api/types";
import { Card } from "../shared";

const SEVERITY_ORDER: Severity[] = ["error", "warning", "info"];

interface Props {
  findings: ConformanceFinding[];
  byRule: Record<string, number>;
}

export function ConformanceFindings({ findings, byRule }: Props) {
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [rule, setRule] = useState<string>("all");

  const visible = useMemo(
    () =>
      findings.filter(
        (f) =>
          (severity === "all" || f.severity === severity) &&
          (rule === "all" || f.rule_id === rule),
      ),
    [findings, severity, rule],
  );

  return (
    <Card title={`Conformance findings (${visible.length} of ${findings.length})`}>
      <div className="filter-row">
        <label>
          Severity
          <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "all")}>
            <option value="all">all</option>
            {SEVERITY_ORDER.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Rule
          <select value={rule} onChange={(e) => setRule(e.target.value)}>
            <option value="all">all</option>
            {Object.entries(byRule)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([id, count]) => (
                <option key={id} value={id}>
                  {id} ({count})
                </option>
              ))}
          </select>
        </label>
      </div>

      {visible.length === 0 ? (
        <p className="muted">No findings match these filters.</p>
      ) : (
        <table className="findings-table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Rule</th>
              <th>Subject</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((f, i) => (
              <tr key={`${f.rule_id}:${f.subject_id}:${i}`}>
                <td>
                  <span className={`sev sev-${f.severity}`}>{f.severity}</span>
                  {/* A rule reduced because the meta-class it governs has no
                      instances yet - it will escalate on its own once they exist. */}
                  {f.degraded && (
                    <span className="badge" title={f.degraded_reason ?? "severity reduced"}>
                      degraded
                    </span>
                  )}
                </td>
                <td className="mono">{f.rule_id}</td>
                <td className="mono">{f.subject_id}</td>
                <td>
                  {f.message}
                  {f.remediation && <div className="muted small">→ {f.remediation}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
