import type {
  AdapterResult, AlertCase, AlertSnapshot, DriftReport, ExplainabilityInsights, FairnessInsights, FeatureRecord, Health,
  Inspection, InterventionInsights, Mapping, Meta, ModelCard, ModelInsights, MonitoringSummary, PipelineRun, Prediction,
  RecentPrediction, RescuePlan, Scenario, SchemaPayload, StressResult, TriagePlan,
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

const WAKING = new Set([502, 503, 504]);
const WAKE_RETRIES = 14;
const pause = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

/** The host sleeps when idle: a new instance answers 503 for ~15 s, so ride it out quietly. */
async function send(path: string, init?: RequestInit): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(`${BASE}${path}`, init);
      if (!WAKING.has(response.status) || attempt >= WAKE_RETRIES) return response;
    } catch {
      if (attempt >= WAKE_RETRIES) throw new ApiError(0, "Cannot reach the API. Check your connection and try again.");
    }
    await pause(1500);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const response = await send(path, {
    ...init,
    headers: isForm ? init?.headers : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
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
  ping: async () => {
    const response = await fetch(`${BASE}/health`);
    if (!response.ok) throw new ApiError(response.status, "warming");
    return (await response.json()) as Health;
  },
  predict: (features: FeatureRecord, explain = true, reference?: string) =>
    request<Prediction>(`/predict?include_explanation=${explain}${reference ? `&student_reference=${encodeURIComponent(reference)}` : ""}`,
      { method: "POST", body: JSON.stringify(features) }),
  alerts: () => request<AlertSnapshot>("/alerts?limit=200"),
  acknowledge: (id: string, assignee: string, note: string) =>
    request<AlertCase>(`/alerts/${id}/acknowledge`, { method: "POST", body: JSON.stringify({ assignee, note }) }),
  restoreAlerts: (cases: AlertCase[]) => request<{ restored: number }>("/alerts/restore", { method: "POST", body: JSON.stringify({ cases }) }),
  inspect: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Inspection>("/adapter/inspect", { method: "POST", body: form });
  },
  scoreUpload: (file: File, mapping: Mapping, cohort: string, asOf?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mapping", JSON.stringify(mapping));
    form.append("cohort", cohort);
    if (asOf) form.append("as_of", asOf);
    return request<AdapterResult>("/adapter/score", { method: "POST", body: form });
  },
  rescue: (student: FeatureRecord, target = 0.5) =>
    request<RescuePlan>("/lab/rescue", { method: "POST", body: JSON.stringify({ student, target }) }),
  scenarios: () => request<{ scenarios: Scenario[] }>("/lab/scenarios"),
  triage: (students: FeatureRecord[], advisorHours: number, responseRate: number) =>
    request<TriagePlan>("/lab/triage", { method: "POST", body: JSON.stringify({ students, advisor_hours: advisorHours, response_rate: responseRate }) }),
  stress: (students: FeatureRecord[], scenario: string, engagement = 1, scoreShift = 0, delayShift = 0) =>
    request<StressResult>("/lab/stress", { method: "POST", body: JSON.stringify({ students, scenario, engagement, score_shift: scoreShift, delay_shift: delayShift }) }),
  insightsModels: () => request<ModelInsights>("/insights/models"),
  insightsExplainability: () => request<ExplainabilityInsights>("/insights/explainability"),
  insightsFairness: () => request<FairnessInsights>("/insights/fairness"),
  insightsInterventions: () => request<InterventionInsights>("/insights/interventions"),
  insightsPipeline: () => request<{ runs: PipelineRun[] }>("/insights/pipeline"),
  monitoringSummary: () => request<MonitoringSummary>("/monitoring/summary"),
  monitoringDrift: () => request<DriftReport>("/monitoring/drift"),
  monitoringRecent: (limit = 20) => request<{ items: RecentPrediction[] }>(`/monitoring/recent?limit=${limit}`),
};
