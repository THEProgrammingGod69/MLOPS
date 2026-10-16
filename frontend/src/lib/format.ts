export const pct = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined || Number.isNaN(value) ? "—" : `${(value * 100).toFixed(digits)}%`;

export const num = (value: number | null | undefined, digits = 3): string =>
  value === null || value === undefined || Number.isNaN(value) ? "—" : value.toFixed(digits);

export const int = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : Math.round(value).toLocaleString();

export const ms = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : value < 10 ? `${value.toFixed(1)} ms` : `${Math.round(value)} ms`;

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  const hours = Math.floor(seconds / 3600);
  if (hours < 48) return `${hours}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

export function timeAgo(unixSeconds: number): string {
  const delta = Math.max(0, Date.now() / 1000 - unixSeconds);
  if (delta < 5) return "just now";
  if (delta < 60) return `${Math.round(delta)}s ago`;
  if (delta < 3600) return `${Math.round(delta / 60)}m ago`;
  return `${Math.round(delta / 3600)}h ago`;
}

export const titleCase = (value: string): string =>
  value.replace(/[_/]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const METRIC_LABEL: Record<string, string> = {
  roc_auc: "ROC AUC",
  pr_auc: "PR AUC",
  f1: "F1",
  recall: "Recall",
  precision: "Precision",
  accuracy: "Accuracy",
  specificity: "Specificity",
  log_loss: "Log loss",
  brier_score: "Brier",
  ece: "ECE",
};

export const MODEL_LABEL: Record<string, string> = { lr: "Logistic Regression", rf: "Random Forest", xgb: "XGBoost" };
