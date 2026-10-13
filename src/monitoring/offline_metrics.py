"""Prometheus collector that publishes the offline evaluation results as gauges.

Batch evaluation (model comparison, fairness audit, calibration, risk-tier
validation, SHAP, pipeline runs) happens outside the request path. Exporting the
latest results next to the live metrics lets one Grafana dashboard show both
"how the service behaves now" and "how good and how fair the deployed model was
when it was validated". Values are read through ``ReportStore`` at scrape time,
so re-running a batch job updates Grafana without restarting the API.
"""
from prometheus_client.core import GaugeMetricFamily

from src.monitoring.report_store import ReportStore

PREFIX = "student_dropout_offline"
TIER_METRICS = ("count", "percentage", "withdrawal_rate", "precision_cumulative",
                "recall_cumulative", "f1_cumulative", "fpr_cumulative")
SWEEP_METRICS = ("alert_rate", "precision", "recall", "f1", "fpr")
CALIBRATION_METRICS = ("brier_score", "ece", "log_loss", "roc_auc", "pr_auc")
DISPARITY_METRICS = ("demographic_parity_difference", "demographic_parity_ratio",
                     "equalized_odds_difference")
GROUP_METRICS = ("selection_rate", "true_positive_rate", "false_positive_rate", "precision", "recall")
MITIGATION_METRICS = ("accuracy", "precision", "recall", "f1", "demographic_parity_difference",
                      "equalized_odds_difference")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class OfflineMetricsCollector:
    def __init__(self, store: ReportStore):
        self.store = store

    def describe(self):
        # Returning no descriptions keeps registration cheap (no report I/O at import).
        return []

    def collect(self):
        store = self.store

        model = GaugeMetricFamily(f"{PREFIX}_model_metric",
                                  "Offline classification metric per model and data split",
                                  labels=["model", "split", "metric"])
        for row in store.model_comparison():
            model.add_metric([row["model"], row["split"], row["metric"]], row["value"])
        yield model

        calibration = GaugeMetricFamily(f"{PREFIX}_calibration_metric",
                                        "Calibration quality per model and calibration method",
                                        labels=["model", "method", "metric"])
        for row in store.calibration():
            for metric in CALIBRATION_METRICS:
                if _is_number(row.get(metric)):
                    calibration.add_metric([row["model"], row["calibration_method"], metric], row[metric])
        yield calibration

        tiers = GaugeMetricFamily(f"{PREFIX}_risk_tier_metric",
                                  "Validation outcome statistics per risk tier",
                                  labels=["risk_tier", "metric"])
        for row in store.risk_tier_validation():
            for metric in TIER_METRICS:
                if _is_number(row.get(metric)):
                    tiers.add_metric([row["risk_tier"], metric], row[metric])
        yield tiers

        sweep = GaugeMetricFamily(f"{PREFIX}_threshold_sweep",
                                  "Validation alert metrics if a single risk threshold were used",
                                  labels=["threshold", "metric"])
        for row in store.risk_threshold_sweep():
            threshold = f"{row['risk_threshold']:.2f}"
            for metric in SWEEP_METRICS:
                if _is_number(row.get(metric)):
                    sweep.add_metric([threshold, metric], row[metric])
        yield sweep

        shap = GaugeMetricFamily(f"{PREFIX}_shap_importance",
                                 "Global mean |SHAP| per transformed feature (validation set)",
                                 labels=["feature"])
        for row in store.shap_importance():
            if _is_number(row.get("mean_abs_shap")):
                shap.add_metric([row["feature"]], row["mean_abs_shap"])
        yield shap

        disparity = GaugeMetricFamily(f"{PREFIX}_fairness_disparity",
                                      "Fairness disparity per model, split and sensitive attribute",
                                      labels=["model", "split", "attribute", "metric"])
        for row in store.fairness_disparity():
            for metric in DISPARITY_METRICS:
                if _is_number(row.get(metric)):
                    disparity.add_metric([row["model"], row["split"], row["sensitive_attribute"], metric],
                                         row[metric])
        yield disparity

        groups = GaugeMetricFamily(f"{PREFIX}_group_metric",
                                   "Per-group outcome metrics from the fairness audit",
                                   labels=["model", "split", "attribute", "group", "metric"])
        for row in store.group_metrics():
            for metric in GROUP_METRICS:
                if _is_number(row.get(metric)):
                    groups.add_metric([row["model"], row["split"], row["sensitive_attribute"],
                                       str(row["group"]), metric], row[metric])
        yield groups

        mitigation = GaugeMetricFamily(f"{PREFIX}_mitigation_metric",
                                       "Fairness mitigation results",
                                       labels=["model", "attribute", "method", "constraint", "split", "metric"])
        for row in store.mitigation():
            for metric in MITIGATION_METRICS:
                if _is_number(row.get(metric)):
                    mitigation.add_metric([row["model"], row["sensitive_attribute"], row["mitigation_method"],
                                           row["fairness_constraint"], row["split"], metric], row[metric])
        yield mitigation

        runs = store.pipeline_runs()
        pipeline = GaugeMetricFamily(f"{PREFIX}_pipeline_validation_metric",
                                     "Validation metrics of the latest automated pipeline run",
                                     labels=["metric"])
        pipeline_runs = GaugeMetricFamily(f"{PREFIX}_pipeline_runs",
                                          "Number of automated pipeline run reports on disk")
        pipeline_runs.add_metric([], len(runs))
        if runs:
            for key, value in (runs[-1].get("validation_metrics") or {}).items():
                if _is_number(value):
                    pipeline.add_metric([key.removeprefix("val_")], value)
        yield pipeline
        yield pipeline_runs
