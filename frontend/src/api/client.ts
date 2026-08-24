import type {
  ConfigResponse,
  CorrectionRequest,
  CorrectionResponse,
  FeedbackAnalysisResponse,
  HealthResponse,
  ValidateRequest,
  ValidateResponse,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function normalizeError(payload: unknown, status: number): ApiError {
  let message = `Request failed (${status})`;
  if (payload && typeof payload === "object") {
    const err = (payload as { error?: unknown }).error;
    if (typeof err === "string") {
      message = err;
    } else if (err && typeof err === "object") {
      const nested = err as { error?: unknown; detail?: unknown };
      if (typeof nested.error === "string") message = nested.error;
      if (nested.detail !== undefined && nested.error !== undefined) {
        message = `${String(nested.error)}: ${String(nested.detail)}`;
      } else if (typeof nested.detail === "string") {
        message = nested.detail;
      }
    }
  }
  return new ApiError(message, status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (e) {
    throw new ApiError(`Network error: ${(e as Error).message}`, 0);
  }

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    throw normalizeError(payload, response.status);
  }
  return payload as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function validate(req: ValidateRequest): Promise<ValidateResponse> {
  return request<ValidateResponse>("/api/validate", jsonInit("POST", req));
}

export async function getConfig(): Promise<ConfigResponse> {
  return request<ConfigResponse>("/api/config");
}

export async function getHealth(force = false): Promise<HealthResponse> {
  const path = force ? "/api/health?force=true" : "/api/health";
  return request<HealthResponse>(path);
}

export async function submitCorrection(
  req: CorrectionRequest,
): Promise<CorrectionResponse> {
  return request<CorrectionResponse>("/api/feedback/correct", jsonInit("POST", req));
}

export async function getFeedbackAnalysis(
  days: number,
): Promise<FeedbackAnalysisResponse> {
  return request<FeedbackAnalysisResponse>(
    `/api/feedback/analysis?days=${encodeURIComponent(days)}`,
  );
}
