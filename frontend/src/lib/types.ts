// Mirrors the FastAPI /api/v1 response models (src/api/schemas.py and routers).

export type RiskTier = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
export const RISK_TIERS: RiskTier[] = ["LOW", "MODERATE", "HIGH", "CRITICAL"];

export type FeatureValue = number | string | null;
export type FeatureRecord = Record<string, FeatureValue>;

export interface FeatureSpec {
  name: string;
  label: string;
  group: "enrollment" | "assessment" | "engagement";
  description: string;
  kind: "integer" | "number" | "category";
  min: number | null;
  max: number | null;
  step: number | null;
  default: FeatureValue;
  unit: string | null;
  nullable: boolean;
  null_label: string | null;
  options: string[] | null;
}

export interface SampleProfile {
  id: string;
  label: string;
  description: string;
  features: FeatureRecord;
}

export interface SchemaPayload {
  features: FeatureSpec[];
  groups: { id: string; label: string; description: string }[];
  course_catalog: Record<string, Record<string, number>>;
  samples: SampleProfile[];
  sensitive_attribute: { name: string; label: string; options: string[]; description: string };
}

export interface ComponentState {
  loaded: boolean;
  detail: string | null;
}

export interface Health {
  status: "healthy" | "unhealthy";
  model_loaded: boolean;
  service: string;
  version: string;
  model_version: string;
  uptime_seconds: number;
  components: Record<"model" | "intervention_engine" | "fairness_mitigator" | "explainer", ComponentState>;
}

export interface Meta {
  service: string;
  version: string;
  links: { grafana: string; prometheus: string; api_docs: string; metrics: string };
}

export interface TierRule {
  min_probability: number;
  max_probability: number;
}

export interface InterventionRule {
  intervention_level: string;
  human_review_required: boolean;
  recommended_actions: string[];
}

export interface ModelCard {
  loaded: boolean;
  version: string;
  artifact: { path: string; sha256: string; size_bytes: number; modified_at: string } | null;
  loaded_at: string;
  estimator: string | null;
  n_raw_features: number;
  n_transformed_features: number | null;
  hyperparameters: Record<string, number | string>;
  risk_tiers: Record<string, TierRule> | null;
  intervention_rules: Record<string, InterventionRule> | null;
  offline_metrics: Record<string, Record<string, number>>;
  components: Health["components"];
}

export interface Contribution {
  feature: string;
  label: string;
  value: FeatureValue;
  contribution: number;
}

export interface Prediction {
  risk_probability: number;
  risk_tier: RiskTier;
  priority_score: number;
  human_review_required: boolean;
  intervention_level: string;
  recommended_actions: string[];
  fairness_adjusted_decision: number | null;
  fairness_status: string;
  prediction_id: string;
  model_version: string;
  latency_ms: number;
  missing_features: string[];
  explanation: { backend: string; base_value: number; contributions: Contribution[] } | null;
}

export interface BatchRow {
  index: number;
  record_id: string | null;
  risk_probability: number;
  risk_tier: RiskTier;
  intervention_level: string;
  human_review_required: boolean;
  fairness_adjusted_decision: number | null;
  fairness_status: string;
  missing_features: string[];
  top_drivers: Contribution[] | null;
}

export interface BatchResponse {
  model_version: string;
  latency_ms: number;
  summary: {
    count: number;
    mean_risk_probability: number;
    median_risk_probability: number;
    max_risk_probability: number;
    human_review_count: number;
    human_review_rate: number;
    tier_counts: Record<RiskTier, number>;
  };
  results: BatchRow[];
}

export interface WindowStats {
  size: number;
  capacity: number;
  mean_risk_probability: number | null;
  p90_risk_probability: number | null;
  human_review_rate: number | null;
  tier_share: Record<RiskTier, number>;
  risk_histogram: number[];
  latency_ms: { p50: number | null; p95: number | null; p99: number | null };
}

export interface MonitoringSummary {
  uptime_seconds: number;
  model_version: string;
  totals: {
    predictions: number;
    single: number;
    batch: number;
    human_review: number;
    errors: number;
    tiers: Record<RiskTier, number>;
  };
  window: WindowStats;
  drift: {
    available: boolean;
    reference_source: string | null;
    min_samples: number;
    min_samples_categorical: number;
    features_tracked: number;
    moderate: number;
    substantial: number;
    ready: boolean;
  };
}

export type DriftStatus = "no meaningful drift" | "moderate drift" | "substantial drift";

export interface DriftFeature {
  feature: string;
  metric: "PSI" | "TVD";
  value: number;
  status: DriftStatus;
  window_mean: number | null;
  reference_mean: number | null;
  window_missing_rate: number;
  reference_missing_rate: number;
}

export interface DriftReport {
  ready: boolean;
  window_size: number;
  window_capacity: number;
  min_samples: number;
  min_samples_categorical: number;
  thresholds: { psi: [number, number]; tvd: [number, number] };
  reference: { source: string | null; approximate: boolean | null; generated_at: string | null; n_rows: number | null; note?: string | null };
  features: DriftFeature[];
}

export interface RecentPrediction {
  prediction_id: string;
  timestamp: number;
  source: "single" | "batch";
  risk_probability: number;
  risk_tier: RiskTier;
  intervention_level: string;
  human_review_required: boolean;
  fairness_status: string | null;
  code_module: string | null;
  code_presentation: string | null;
  top_driver: string | null;
}

export type Row = Record<string, number | string | boolean | null>;

export interface ModelInsights {
  comparison: { model: string; model_name: string; split: string; metric: string; value: number }[];
  calibration: Row[];
  calibration_audit: Row[];
  risk_threshold_sweep: Row[];
  selective_threshold_sweep: Row[];
  integrated_summary: Row[];
}

export interface ExplainabilityInsights {
  shap: { feature: string; label: string; mean_abs_shap: number; rank: number }[];
  gain: { feature: string; label: string; importance: number }[];
}

export interface FairnessInsights {
  disparity: Row[];
  groups: Row[];
  mitigation: Row[];
  compatibility: Row[];
}

export interface InterventionInsights {
  tiers: Row[];
  mapping: Row[];
  thresholds: Record<string, TierRule> | null;
}

export interface PipelineRun {
  pipeline_step: string;
  execution_timestamp: string;
  execution_time_seconds: number;
  data_quality: Record<string, number>;
  training: Record<string, number | string>;
  validation_metrics: Record<string, number>;
  mlflow_run_id: string;
  report_file: string;
}
