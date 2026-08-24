import { useState } from "react";

import { ApiError, submitCorrection } from "../../api/client";
import type { CorrectionRequest, VerdictOut } from "../../api/types";
import { Button } from "../shared/Button";

const LABELS = ["supported", "contradicted", "partial", "unknown"] as const;

interface FeedbackCorrectionFormProps {
  verdict: VerdictOut;
  documentId?: string;
  onCorrected?: () => void;
}

export function FeedbackCorrectionForm({
  verdict,
  documentId,
  onCorrected,
}: FeedbackCorrectionFormProps) {
  const [open, setOpen] = useState(false);
  const [actualLabel, setActualLabel] = useState<(typeof LABELS)[number]>("supported");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "recorded">("idle");
  const [error, setError] = useState<string | null>(null);

  if (!verdict.feedback_id && !verdict.assertion_id) return null;

  const submit = async () => {
    setStatus("submitting");
    setError(null);
    const req: CorrectionRequest = {
      feedback_id: verdict.feedback_id ?? undefined,
      actual_label: actualLabel,
      reason: reason.trim() ? reason.trim() : undefined,
      document_id: documentId ?? undefined,
      assertion_id: verdict.assertion_id,
      subject: verdict.subject,
      relation: verdict.relation,
      object: verdict.object,
      predicted_label: verdict.label,
      predicted_score: verdict.score,
      retrieval_sources: verdict.retrieval_sources,
    };
    try {
      await submitCorrection(req);
      setStatus("recorded");
      onCorrected?.();
    } catch (e) {
      setStatus("idle");
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not record correction. Please try again.",
      );
    }
  };

  if (status === "recorded") {
    return (
      <p style={{ color: "var(--green)", fontSize: "0.82rem" }}>
        ✓ Correction recorded — thanks.
      </p>
    );
  }

  return (
    <div style={{ marginTop: "0.5rem" }}>
      {!open ? (
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Correct this verdict
        </Button>
      ) : (
        <div>
          <label>
            Actual label
            <select
              value={actualLabel}
              onChange={(e) => setActualLabel(e.target.value as (typeof LABELS)[number])}
            >
              {LABELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label>
            Reason (optional)
            <textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is the predicted label wrong?"
            />
          </label>
          {error ? (
            <p className="card-error" role="alert">
              {error}
            </p>
          ) : null}
          <div className="submit-row">
            <Button onClick={submit} loading={status === "submitting"}>
              Submit correction
            </Button>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
