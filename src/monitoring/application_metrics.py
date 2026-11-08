"""Prometheus metrics exposed by the inference service on ``/metrics``.

The first three metrics are the original Step 2.13 contract (alert rules and
tests depend on their names). Everything below them adds the signals the Grafana
dashboard needs: RED metrics per route, prediction outcome mix, risk score
distribution, fairness post-processing and explanation usage, input data quality,
batch scoring and component health. Label values are bounded enums (risk tiers,
intervention levels, route templates), never student-level data.
"""
import time

from fastapi import Request, Response
from prometheus_client import (CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, Histogram, Info,
                               generate_latest)

from src.models.train_baselines import PREDICTIVE_FEATURES

RISK_TIERS = ("LOW", "MODERATE", "HIGH", "CRITICAL")
SOURCES = ("single", "batch")

# --- Original metrics (names are a contract) ------------------------------------------
PREDICTION_REQUESTS = Counter(
    'student_dropout_prediction_requests_total',
    'Total number of prediction requests'
)
PREDICTION_ERRORS = Counter(
    'student_dropout_prediction_errors_total',
    'Total number of prediction request errors'
)
PREDICTION_LATENCY = Histogram(
    'student_dropout_prediction_latency_seconds',
    'Latency of prediction requests in seconds'
)

# --- HTTP (RED) ---------------------------------------------------------------------------
HTTP_REQUESTS = Counter(
    'student_dropout_http_requests_total',
    'HTTP requests by method, route template and status code',
    ['method', 'route', 'status']
)
HTTP_LATENCY = Histogram(
    'student_dropout_http_request_duration_seconds',
    'HTTP request duration by method and route template',
    ['method', 'route'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)
)
HTTP_IN_PROGRESS = Gauge(
    'student_dropout_http_requests_in_progress',
    'HTTP requests currently being served'
)

# --- Prediction outcomes ------------------------------------------------------------------
PREDICTIONS = Counter(
    'student_dropout_predictions_total',
    'Students scored, by risk tier and request source (single or batch)',
    ['risk_tier', 'source']
)
INTERVENTIONS = Counter(
    'student_dropout_interventions_total',
    'Recommended intervention level per scored student',
    ['intervention_level']
)
HUMAN_REVIEW = Counter(
    'student_dropout_human_review_required_total',
    'Scored students routed to human review'
)
RISK_PROBABILITY = Histogram(
    'student_dropout_risk_probability',
    'Distribution of predicted dropout probabilities',
    buckets=tuple(round(0.05 * i, 2) for i in range(1, 21))
)
FAIRNESS_DECISIONS = Counter(
    'student_dropout_fairness_decisions_total',
    'Fairness post-processing outcomes (status and binary decision)',
    ['status', 'decision']
)

# --- Explanations, batches, data quality --------------------------------------------------
EXPLANATIONS = Counter(
    'student_dropout_explanations_total',
    'SHAP explanations computed, by backend',
    ['backend']
)
EXPLANATION_LATENCY = Histogram(
    'student_dropout_explanation_latency_seconds',
    'Time spent computing SHAP explanations per request'
)
BATCH_REQUESTS = Counter(
    'student_dropout_batch_requests_total',
    'Batch scoring requests'
)
BATCH_SIZE = Histogram(
    'student_dropout_batch_size',
    'Students per batch scoring request',
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000)
)
BATCH_LATENCY = Histogram(
    'student_dropout_batch_latency_seconds',
    'End-to-end batch scoring latency',
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
)
MISSING_INPUTS = Counter(
    'student_dropout_missing_feature_values_total',
    'Null input values received per feature',
    ['feature']
)

# --- Service / model state -----------------------------------------------------------------
MODEL_LOADED = Gauge('student_dropout_model_loaded', 'Whether the risk model is loaded (1) or not (0)')
COMPONENT_UP = Gauge('student_dropout_component_up', 'Health of each serving component', ['component'])
MODEL_INFO = Info('student_dropout_model', 'Served model artifact metadata')
APP_START_TIME = Gauge('student_dropout_app_start_time_seconds', 'Unix time the API process started')
APP_START_TIME.set(time.time())

# --- Alert desk: students at or above the alert threshold (default 50 %) ------------------
ALERT_OPEN = Gauge(
    'student_dropout_alert_open',
    'Dropout probability of each open at-risk case (bounded rings, pseudonymous student label)',
    ['student', 'tier', 'driver', 'cohort', 'origin']
)
ALERTS_OPEN = Gauge('student_dropout_alerts_open', 'Open at-risk cases by origin', ['origin'])
ALERTS_RAISED = Counter('student_dropout_alerts_raised_total', 'At-risk cases opened', ['origin'])
ALERTS_ACKNOWLEDGED = Counter('student_dropout_alerts_acknowledged_total', 'At-risk cases acknowledged', ['origin'])
ALERT_ACK_SECONDS = Histogram(
    'student_dropout_alert_ack_seconds',
    'Time from a case being opened to an advisor acknowledging it',
    buckets=(10, 30, 60, 300, 900, 3600, 14400, 86400)
)

# --- Institution data adapter ---------------------------------------------------------------
ADAPTER_RUNS = Counter('student_dropout_adapter_runs_total', 'Institution files scored through the adapter', ['verdict'])
ADAPTER_ROWS = Counter('student_dropout_adapter_rows_total', 'Rows scored through the adapter')
ADAPTER_FIT = Gauge('student_dropout_adapter_fit_score', 'Institution Fit Score of the most recent adapter run (0-100)')

# Pre-create bounded label sets so dashboards show explicit zeros instead of "No data".
for _tier in RISK_TIERS:
    for _source in SOURCES:
        PREDICTIONS.labels(risk_tier=_tier, source=_source)
for _feature in PREDICTIVE_FEATURES:
    MISSING_INPUTS.labels(feature=_feature)


def register_collector(collector) -> None:
    """Register a custom collector once (module reloads in tests must not duplicate it)."""
    if not getattr(collector, "_registered", False):
        REGISTRY.register(collector)
        collector._registered = True


def metrics_endpoint(request: Request):
    """FastAPI route handler for /metrics"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
