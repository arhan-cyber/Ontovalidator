import { useCallback, useState } from "react";

import { ApiError, validate } from "../api/client";
import type { ValidateRequest, ValidateResponse } from "../api/types";
import { DetailLevelToggle } from "../components/shared/DetailLevelToggle";
import { ErrorBanner } from "../components/shared/ErrorBanner";
import { LoadingSpinner } from "../components/shared/LoadingSpinner";
import { DocumentForm } from "../components/validate/DocumentForm";
import { ResultsSummary } from "../components/validate/ResultsSummary";
import { VerdictCard } from "../components/validate/VerdictCard";

export default function ValidatePage() {
  const [result, setResult] = useState<ValidateResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runValidation = useCallback(async (req: ValidateRequest) => {
    setSubmitting(true);
    setError(null);
    try {
      const response = await validate(req);
      setResult(response);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Validation request failed.");
      setResult(null);
    } finally {
      setSubmitting(false);
    }
  }, []);

  return (
    <>
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      <div className="detail-level-row">
        <span className="detail-level-label">Trace detail</span>
        <DetailLevelToggle />
      </div>
      <DocumentForm onSubmit={runValidation} submitting={submitting} />

      {submitting ? <LoadingSpinner message="Validating triples…" /> : null}

      {result && !submitting ? (
        <>
          <ResultsSummary result={result} />
          <section>
            {result.verdicts.map((verdict) => (
              <VerdictCard key={verdict.assertion_id} verdict={verdict} documentId={result.document_id} />
            ))}
          </section>
        </>
      ) : null}
    </>
  );
}
