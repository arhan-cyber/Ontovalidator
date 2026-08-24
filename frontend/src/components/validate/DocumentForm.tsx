import { useEffect, useState } from "react";

import { getConfig } from "../../api/client";
import type { TripleIn, ValidateRequest } from "../../api/types";
import type { ConfigResponse } from "../../api/types";
import { initTriples, TriplesEditor } from "./TriplesEditor";

interface DocumentFormProps {
  onSubmit: (req: ValidateRequest) => void;
  submitting: boolean;
}

export function DocumentForm({ onSubmit, submitting }: DocumentFormProps) {
  const [rawText, setRawText] = useState("");
  const [triples, setTriples] = useState<TripleIn[]>(initTriples());
  const [topK, setTopK] = useState(5);
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [svoExtractor, setSvoExtractor] = useState("");
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    getConfig()
      .then((cfg) => {
        setConfig(cfg);
        if (cfg.available_embedding_models.length > 0) {
          setEmbeddingModel(cfg.embedding_model_name);
        }
        if (cfg.available_svo_extractors.length > 0) {
          setSvoExtractor(cfg.svo_extractor_name);
        }
      })
      .catch(() => {
        /* settings stay manual when /config is unreachable */
      });
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!rawText.trim()) {
      setFormError("Document text must not be empty.");
      return;
    }
    const filled = triples.filter(
      (t) => t.subject.trim() && t.relation.trim() && t.object.trim(),
    );
    if (filled.length === 0) {
      setFormError("At least one complete triple is required.");
      return;
    }
    if (
      triples.some(
        (t) =>
          (t.subject.trim() || t.relation.trim() || t.object.trim()) &&
          !(t.subject.trim() && t.relation.trim() && t.object.trim()),
      )
    ) {
      setFormError("Every partially-filled triple needs all three fields.");
      return;
    }
    onSubmit({
      raw_text: rawText,
      triples: filled,
      top_k: topK,
      embedding_model: embeddingModel || null,
      svo_extractor: svoExtractor || null,
    });
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h3 className="card-title">Document &amp; Triples</h3>
      <label>
        Document text
        <textarea
          rows={8}
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          placeholder="Paste the document to verify against…"
        />
      </label>

      <div style={{ margin: "1rem 0" }}>
        <TriplesEditor triples={triples} onChange={setTriples} />
      </div>

      <details open={false}>
        <summary>Settings</summary>
        <div className="settings-grid" style={{ marginTop: "0.75rem" }}>
          <label>
            Embedding model
            <select
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
            >
              {(config?.available_embedding_models ?? ["simple", "transformer"]).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label>
            SVO extractor
            <select value={svoExtractor} onChange={(e) => setSvoExtractor(e.target.value)}>
              {(config?.available_svo_extractors ?? ["mock", "transformer"]).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label>
            Top K
            <input
              type="number"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
          </label>
        </div>
      </details>

      {formError ? (
        <p className="card-error" role="alert">
          {formError}
        </p>
      ) : null}

      <div className="submit-row">
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Validating…" : "Validate Triples"}
        </button>
        {config ? (
          <span style={{ color: "var(--gray)", fontSize: "0.78rem" }}>
            mode: {config.backend_mode} · models: {config.embedding_model_name}/
            {config.svo_extractor_name}
          </span>
        ) : null}
      </div>
    </form>
  );
}
