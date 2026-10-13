"""Wires serving events into Prometheus metrics and the live monitor.

Routes call ``record_predictions`` after a successful scoring call and
``record_error`` on failure; this module owns the process-wide ``LiveMonitor``
and ``ReportStore`` singletons and registers their Prometheus collectors.
"""
from typing import List, Optional

import yaml

from src.api.inference import fairness_metric_status, inference_service
from src.api.settings import settings
from src.monitoring import application_metrics as m
from src.monitoring.live_monitor import LiveMonitor, LiveMonitorCollector, load_reference_profile
from src.monitoring.offline_metrics import OfflineMetricsCollector
from src.monitoring.report_store import ReportStore


def _drift_thresholds():
    try:
        with open(settings.monitoring_config_path, "r") as f:
            drift = yaml.safe_load(f)["monitoring"]["drift"]
        return ((drift["psi_thresholds"]["no_drift"], drift["psi_thresholds"]["moderate_drift"]),
                (drift["tvd_thresholds"]["no_drift"], drift["tvd_thresholds"]["moderate_drift"]))
    except (OSError, KeyError, TypeError):
        return (0.10, 0.25), (0.05, 0.15)


_psi, _tvd = _drift_thresholds()
live_monitor = LiveMonitor(
    reference_profile=load_reference_profile(settings.reference_profile_path),
    window_size=settings.drift_window_size,
    min_samples=settings.drift_min_samples,
    min_samples_categorical=settings.drift_min_samples_categorical,
    recent_size=settings.recent_predictions_size,
    psi_thresholds=_psi,
    tvd_thresholds=_tvd,
)
report_store = ReportStore(settings.reports_dir)

_live_collector = LiveMonitorCollector(live_monitor)
_offline_collector = OfflineMetricsCollector(report_store)
m.register_collector(_live_collector)
m.register_collector(_offline_collector)


def publish_service_state() -> None:
    """Expose model/component health and artifact metadata as gauges."""
    m.MODEL_LOADED.set(1 if inference_service.is_healthy() else 0)
    for component, state in inference_service.components.items():
        m.COMPONENT_UP.labels(component=component).set(1 if state["loaded"] else 0)
    explainer = inference_service.components["explainer"]
    m.MODEL_INFO.info({
        "version": inference_service.model_version,
        "estimator": inference_service.components["model"]["detail"] or "unavailable",
        "explainer_backend": explainer["detail"] if explainer["loaded"] else "unavailable",
        "fairness_mitigator": "loaded" if inference_service.components["fairness_mitigator"]["loaded"] else "unavailable",
        "reference_profile": str((live_monitor.profile or {}).get("source", "none")),
    })


def record_predictions(results: List[dict], source: str, latency_seconds: Optional[float] = None) -> None:
    explanation_seconds = 0.0
    explained_backend = None
    for result in results:
        m.PREDICTIONS.labels(risk_tier=result["risk_tier"], source=source).inc()
        m.INTERVENTIONS.labels(intervention_level=result["intervention_level"]).inc()
        m.RISK_PROBABILITY.observe(result["risk_probability"])
        if result["human_review_required"]:
            m.HUMAN_REVIEW.inc()
        decision = result["fairness_adjusted_decision"]
        m.FAIRNESS_DECISIONS.labels(status=fairness_metric_status(result["fairness_status"]),
                                    decision="none" if decision is None else str(decision)).inc()
        for feature in result["missing_features"]:
            m.MISSING_INPUTS.labels(feature=feature).inc()
        if result.get("explanation"):
            explanation_seconds += result.get("explanation_seconds", 0.0)
            explained_backend = result["explanation"]["backend"]
    if explained_backend is not None:
        m.EXPLANATIONS.labels(backend=explained_backend).inc(len(results))
        m.EXPLANATION_LATENCY.observe(explanation_seconds)
    live_monitor.observe([r["inputs"] for r in results], results, source=source,
                         latency_seconds=latency_seconds)


def record_error() -> None:
    m.PREDICTION_ERRORS.inc()
    live_monitor.record_error()


publish_service_state()
