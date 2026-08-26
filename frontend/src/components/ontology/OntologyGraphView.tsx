import { useMemo, useState } from "react";

import type { OntologyGraphResponse, OntologyReport } from "../../api/types";
import { Card } from "../shared";

interface Props {
  graph: OntologyGraphResponse;
  report: OntologyReport | null;
}

/**
 * Node list grouped by meta-class, coloured on both axes independently.
 *
 * Deliberately a grouped list rather than a force-directed diagram: with 74
 * nodes and 85 edges a spring layout is a hairball, and the question a
 * reviewer actually has is "which nodes are failing, and on which axis" —
 * which a sorted, filterable list answers directly.
 */
export function OntologyGraphView({ graph, report }: Props) {
  const [showOnlyProblems, setShowOnlyProblems] = useState(false);

  const grouped = useMemo(() => {
    const byClass: Record<string, typeof graph.nodes> = {};
    for (const node of graph.nodes) {
      const status = report?.node_status[node.id];
      const grounding = report?.grounding.node_grounding[node.id]?.status;
      const isProblem =
        status?.conformance === "fail" || grounding === "contradicted";
      if (showOnlyProblems && !isProblem) continue;
      (byClass[node.meta_class] ??= []).push(node);
    }
    return byClass;
  }, [graph.nodes, report, showOnlyProblems]);

  const edgeCount = graph.edges.length;

  return (
    <Card title={`Ontology graph — ${graph.nodes.length} nodes, ${edgeCount} edges`}>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={showOnlyProblems}
          onChange={(e) => setShowOnlyProblems(e.target.checked)}
        />
        Show only nodes failing conformance or contradicted by the documents
      </label>

      {Object.keys(grouped).length === 0 ? (
        <p className="muted">No nodes match.</p>
      ) : (
        Object.entries(grouped)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([metaClass, nodes]) => (
            <div key={metaClass} className="node-group">
              <h4>
                {metaClass} <span className="muted">({nodes.length})</span>
              </h4>
              <ul className="node-list">
                {nodes
                  .slice()
                  .sort((a, b) => a.id.localeCompare(b.id))
                  .map((node) => {
                    const status = report?.node_status[node.id];
                    const grounding =
                      report?.grounding.node_grounding[node.id]?.status ?? "unknown";
                    return (
                      <li key={node.id} className="node-row" title={node.description}>
                        <span className="mono">{node.id}</span>
                        <span className="node-axes">
                          <span
                            className={`axis axis-${status?.conformance ?? "pass"}`}
                            title={
                              status?.failed_rules.length
                                ? `conformance: ${status.failed_rules.join(", ")}`
                                : "conformance: pass"
                            }
                          >
                            {status?.conformance ?? "pass"}
                          </span>
                          {report?.grounding.ran && (
                            <span className={`axis axis-${grounding}`} title="grounding">
                              {grounding}
                            </span>
                          )}
                        </span>
                      </li>
                    );
                  })}
              </ul>
            </div>
          ))
      )}
    </Card>
  );
}
