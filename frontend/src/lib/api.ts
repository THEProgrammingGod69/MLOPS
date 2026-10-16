import type {
  BatchResponse, DriftReport, ExplainabilityInsights, FairnessInsights, FeatureRecord, Health,
  InterventionInsights, Meta, ModelCard, ModelInsights, MonitoringSummary, PipelineRun, Prediction,
  RecentPrediction, SchemaPayload,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422: [{loc: ["body", "students", 3, "vle_total_clicks"], msg: "..."}]
    return detail
      .slice(0, 4)
      .map((d: { loc?: (string | number)[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(" › ")}: ${d.msg ?? "invalid"}`)
      .join("; ");
  }
  return "Unexpected error";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the FastAPI service running on port 8000?");
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) message = describe(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  meta: () => request<Meta>("/meta"),
  model: () => request<ModelCard>("/model"),
  schema: () => request<SchemaPayload>("/schema"),
  predict: (features: FeatureRecord, explain = true) =>
    request<Prediction>(`/predict?include_explanation=${explain}`, { method: "POST", body: JSON.stringify(features) }),
  predictBatch: (students: FeatureRecord[], includeExplanation: boolean) =>
    request<BatchResponse>("/predict/batch", {
      method: "POST",
      body: JSON.stringify({ students, include_explanation: includeExplanation }),
    }),
  insightsModels: () => request<ModelInsights>("/insights/models"),
  insightsExplainability: () => request<ExplainabilityInsights>("/insights/explainability"),
  insightsFairness: () => request<FairnessInsights>("/insights/fairness"),
  insightsInterventions: () => request<InterventionInsights>("/insights/interventions"),
  insightsPipeline: () => request<{ runs: PipelineRun[] }>("/insights/pipeline"),
  monitoringSummary: () => request<MonitoringSummary>("/monitoring/summary"),
  monitoringDrift: () => request<DriftReport>("/monitoring/drift"),
  monitoringRecent: (limit = 20) => request<{ items: RecentPrediction[] }>(`/monitoring/recent?limit=${limit}`),
};
