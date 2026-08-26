import type { OntologyReport } from "../../api/types";
import { Card, StatChip } from "../shared";

interface Props {
  grounding: OntologyReport["grounding"];
}

export function GroundingPanel({ grounding }: Props) {
  if (!grounding.ran) {
    return (
      <Card title="Grounding">
        <p className="muted">
          Not run. Grounding needs a document corpus and a verification engine — run with
          <code> --plane b </code> or <code> both</code>.
        </p>
      </Card>
    );
  }

  const { coverage, by_label: byLabel, vocabulary_gap: gap } = grounding;

  return (
    <Card title="Grounding">
      {/* The demo tier cannot reach `supported` at all, so an unqualified
          "0 supported" would read as a failing ontology rather than as a
          limitation of the retrieval backend. Say which it is. */}
      {grounding.confidence === "low" && (
        <div className="callout callout-warn">
          <strong>Demo-tier retrieval.</strong> <code>supported</code> is unreachable here:
          the demo semantic retriever is token-overlap, not embeddings, and relation matching
          is literal substring. Treat these numbers as a smoke test, not a measurement —
          enable the Elasticsearch/Milvus backends for real grounding.
        </div>
      )}

      <div className="stat-row">
        <StatChip label="supported" value={byLabel.supported ?? 0} />
        <StatChip label="partial" value={byLabel.partial ?? 0} />
        <StatChip label="contradicted" value={byLabel.contradicted ?? 0} />
        <StatChip label="unknown" value={byLabel.unknown ?? 0} />
      </div>

      <div className="stat-row">
        <StatChip
          label="node coverage"
          value={`${coverage.nodes_with_evidence}/${coverage.nodes_total} (${coverage.nodes_pct}%)`}
        />
        <StatChip
          label="edge coverage"
          value={`${coverage.edges_with_evidence}/${coverage.edges_total} (${coverage.edges_pct}%)`}
        />
      </div>

      {gap.measured && (
        <p className="muted small">
          <strong>Vocabulary:</strong> {gap.terms_present}/{gap.terms_total} node labels
          ({gap.present_pct}%) appear anywhere in the corpus; {gap.terms_absent} are never
          mentioned. A term the corpus never uses is a corpus problem; a term that is present
          but unmatched is a retrieval problem — they have opposite fixes.
        </p>
      )}

      {grounding.corpus_documents.length > 0 && (
        <p className="muted small">
          <strong>Corpus:</strong> {grounding.corpus_documents.join(", ")}
        </p>
      )}

      {grounding.contradictions.length > 0 && (
        <>
          <h4>Contradicted claims</h4>
          <p className="muted small">
            The interesting bucket: claims the source documents actively disagree with.
          </p>
          <ul className="contradiction-list">
            {grounding.contradictions.slice(0, 20).map((v, i) => (
              <li key={i} className="mono small">
                {String(v.subject)} · {String(v.relation)} · {String(v.object)}
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
