"""In-process live monitoring: rolling prediction window, live drift and run counters.

Every scored student is appended to a bounded window (inputs + outputs, no
identifiers). From that window the monitor derives

* live data drift against a reference profile of the training split
  (PSI for numeric features, TVD for categorical features, missing values
  treated as their own bin because missingness is itself highly predictive),
* window statistics (mean risk, review rate, tier mix),
* a short log of recent predictions for the web UI.

It is exposed twice: as a Prometheus collector (scraped every few seconds by the
monitoring stack) and as plain dictionaries for ``/api/v1/monitoring/*``.
Everything is O(window_size) and computed lazily at read time, never on the
request path.
"""
import json
import math
import threading
import time
from collections import Counter, deque
from typing import Dict, List, Optional

import numpy as np
from prometheus_client.core import GaugeMetricFamily

RISK_TIERS = ("LOW", "MODERATE", "HIGH", "CRITICAL")
PSI_EPSILON = 1e-4  # same zero-substitution as src.monitoring.drift_detector.calculate_psi
STATUS_CODES = {"no meaningful drift": 0, "moderate drift": 1, "substantial drift": 2}


def load_reference_profile(path: str) -> Optional[dict]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def psi_from_profile(values: np.ndarray, spec: dict) -> float:
    """PSI of ``values`` against a profile entry with ``edges``/``proportions``/``missing_rate``.

    Bins are ``(-inf, e0), [e0, e1), ..., [e_k, +inf)`` plus a dedicated missing bin.
    """
    edges = np.asarray(spec["edges"], dtype=float)
    expected_present = np.asarray(spec["proportions"], dtype=float)
    missing_rate = float(spec.get("missing_rate", 0.0))

    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return 0.0
    is_missing = np.isnan(values)
    present = values[~is_missing]
    counts = np.bincount(np.searchsorted(edges, present, side="right"), minlength=len(edges) + 1)

    expected = np.append(expected_present * (1.0 - missing_rate), missing_rate)
    actual = np.append(counts / n, is_missing.sum() / n)
    expected = np.where(expected > 0, expected, PSI_EPSILON)
    actual = np.where(actual > 0, actual, PSI_EPSILON)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def tvd_from_profile(values: List[str], spec: dict) -> float:
    expected = spec["frequencies"]
    n = len(values)
    if n == 0:
        return 0.0
    observed = Counter(values)
    categories = set(expected) | set(observed)
    return float(0.5 * sum(abs(observed.get(c, 0) / n - expected.get(c, 0.0)) for c in categories))


def classify(value: float, low: float, high: float) -> str:
    if value < low:
        return "no meaningful drift"
    if value < high:
        return "moderate drift"
    return "substantial drift"


class LiveMonitor:
    def __init__(self, reference_profile: Optional[dict], window_size: int = 2000,
                 min_samples: int = 500, min_samples_categorical: int = 1500, recent_size: int = 200,
                 psi_thresholds=(0.10, 0.25), tvd_thresholds=(0.05, 0.15)):
        self.profile = reference_profile
        self.window_size = window_size
        self.min_samples = min_samples
        self.min_samples_categorical = min_samples_categorical
        self.psi_thresholds = psi_thresholds
        self.tvd_thresholds = tvd_thresholds
        self._window = deque(maxlen=window_size)
        self._recent = deque(maxlen=recent_size)
        self._latencies = deque(maxlen=window_size)
        self._lock = threading.Lock()
        self._version = 0
        self._drift_cache = (None, [])
        self.started_at = time.time()
        self.totals = {"predictions": 0, "single": 0, "batch": 0, "human_review": 0,
                       "errors": 0, "tiers": {t: 0 for t in RISK_TIERS}}

    # -- write side -------------------------------------------------------------------
    def observe(self, inputs: List[dict], results: List[dict], source: str,
                latency_seconds: Optional[float] = None) -> None:
        now = time.time()
        with self._lock:
            for features, result in zip(inputs, results):
                tier = result["risk_tier"]
                self._window.append({"features": features, "risk_probability": result["risk_probability"],
                                     "risk_tier": tier, "human_review_required": result["human_review_required"]})
                self._recent.append({
                    "prediction_id": result.get("prediction_id"),
                    "timestamp": now,
                    "source": source,
                    "risk_probability": result["risk_probability"],
                    "risk_tier": tier,
                    "intervention_level": result["intervention_level"],
                    "human_review_required": result["human_review_required"],
                    "fairness_status": result.get("fairness_status"),
                    "code_module": features.get("code_module"),
                    "code_presentation": features.get("code_presentation"),
                    "top_driver": result.get("top_driver"),
                })
                self.totals["predictions"] += 1
                self.totals[source] = self.totals.get(source, 0) + 1
                self.totals["tiers"][tier] = self.totals["tiers"].get(tier, 0) + 1
                self.totals["human_review"] += int(bool(result["human_review_required"]))
            if latency_seconds is not None:
                self._latencies.append(latency_seconds)
            self._version += 1

    def record_error(self) -> None:
        with self._lock:
            self.totals["errors"] += 1

    # -- read side --------------------------------------------------------------------------
    def _snapshot_window(self):
        with self._lock:
            return list(self._window), self._version

    def drift(self) -> List[dict]:
        """Per-feature drift for the current window ([] until min_samples are collected)."""
        window, version = self._snapshot_window()
        cached_version, cached = self._drift_cache
        if cached_version == version:
            return cached
        results: List[dict] = []
        if self.profile and len(window) >= self.min_samples:
            for feature, spec in (self.profile.get("numeric") or {}).items():
                raw = [row["features"].get(feature) for row in window]
                values = np.array([np.nan if v is None else float(v) for v in raw], dtype=float)
                score = psi_from_profile(values, spec)
                present = values[~np.isnan(values)]
                results.append({
                    "feature": feature, "metric": "PSI", "value": round(score, 4),
                    "status": classify(score, *self.psi_thresholds),
                    "window_mean": float(present.mean()) if len(present) else None,
                    "reference_mean": spec.get("mean"),
                    "window_missing_rate": float(np.isnan(values).mean()),
                    "reference_missing_rate": spec.get("missing_rate", 0.0),
                })
            categorical = (self.profile.get("categorical") or {}) if len(window) >= self.min_samples_categorical else {}
            for feature, spec in categorical.items():
                values = ["Missing" if row["features"].get(feature) is None else str(row["features"][feature])
                          for row in window]
                score = tvd_from_profile(values, spec)
                results.append({
                    "feature": feature, "metric": "TVD", "value": round(score, 4),
                    "status": classify(score, *self.tvd_thresholds),
                    "window_mean": None, "reference_mean": None,
                    "window_missing_rate": values.count("Missing") / len(values),
                    "reference_missing_rate": spec.get("frequencies", {}).get("Missing", 0.0),
                })
            results.sort(key=lambda r: r["value"], reverse=True)
        self._drift_cache = (version, results)
        return results

    def window_stats(self) -> dict:
        window, _ = self._snapshot_window()
        n = len(window)
        tiers = Counter(row["risk_tier"] for row in window)
        probs = np.array([row["risk_probability"] for row in window], dtype=float)
        with self._lock:
            latencies = np.array(self._latencies, dtype=float)
        return {
            "size": n,
            "capacity": self.window_size,
            "mean_risk_probability": float(probs.mean()) if n else None,
            "p90_risk_probability": float(np.quantile(probs, 0.9)) if n else None,
            "human_review_rate": float(np.mean([row["human_review_required"] for row in window])) if n else None,
            "tier_share": {t: (tiers.get(t, 0) / n if n else 0.0) for t in RISK_TIERS},
            "risk_histogram": np.histogram(probs, bins=20, range=(0.0, 1.0))[0].tolist() if n else [0] * 20,
            "latency_ms": {
                "p50": float(np.quantile(latencies, 0.5) * 1000) if len(latencies) else None,
                "p95": float(np.quantile(latencies, 0.95) * 1000) if len(latencies) else None,
                "p99": float(np.quantile(latencies, 0.99) * 1000) if len(latencies) else None,
            },
        }

    def recent(self, limit: int = 50) -> List[dict]:
        with self._lock:
            items = list(self._recent)
        return list(reversed(items))[:limit]

    def summary(self) -> dict:
        with self._lock:
            totals = json.loads(json.dumps(self.totals))
        drift = self.drift()
        return {
            "uptime_seconds": time.time() - self.started_at,
            "totals": totals,
            "window": self.window_stats(),
            "drift": {
                "available": bool(self.profile),
                "reference_source": (self.profile or {}).get("source"),
                "min_samples": self.min_samples,
                "min_samples_categorical": self.min_samples_categorical,
                "features_tracked": len((self.profile or {}).get("numeric", {}))
                + len((self.profile or {}).get("categorical", {})),
                "moderate": sum(1 for d in drift if d["status"] == "moderate drift"),
                "substantial": sum(1 for d in drift if d["status"] == "substantial drift"),
                "ready": bool(drift),
            },
        }


class LiveMonitorCollector:
    """Prometheus view of a ``LiveMonitor`` (computed at scrape time)."""

    def __init__(self, monitor: LiveMonitor):
        self.monitor = monitor

    def describe(self):
        return []

    def collect(self):
        stats = self.monitor.window_stats()
        size = GaugeMetricFamily("student_dropout_window_predictions",
                                 "Predictions currently held in the live monitoring window")
        size.add_metric([], stats["size"])
        yield size

        if stats["size"]:
            mean = GaugeMetricFamily("student_dropout_window_mean_risk",
                                     "Mean predicted dropout probability in the live window")
            mean.add_metric([], stats["mean_risk_probability"])
            yield mean
            review = GaugeMetricFamily("student_dropout_window_review_rate",
                                       "Share of the live window flagged for human review")
            review.add_metric([], stats["human_review_rate"])
            yield review
        share = GaugeMetricFamily("student_dropout_window_tier_share",
                                  "Share of each risk tier in the live window", labels=["risk_tier"])
        for tier, value in stats["tier_share"].items():
            share.add_metric([tier], value)
        yield share

        profile = self.monitor.profile or {}
        info = GaugeMetricFamily("student_dropout_reference_profile_info",
                                 "Reference profile used for live drift (value is always 1)",
                                 labels=["source", "features"])
        if profile:
            info.add_metric([str(profile.get("source", "unknown")),
                             str(len(profile.get("numeric", {})) + len(profile.get("categorical", {})))], 1)
        yield info

        drift = self.monitor.drift()
        score = GaugeMetricFamily("student_dropout_feature_drift_score",
                                  "Live drift statistic per feature (PSI numeric, TVD categorical)",
                                  labels=["feature", "metric"])
        status = GaugeMetricFamily("student_dropout_feature_drift_status",
                                   "Drift status per feature: 0 none, 1 moderate, 2 substantial",
                                   labels=["feature"])
        window_mean = GaugeMetricFamily("student_dropout_feature_window_mean",
                                        "Mean of a numeric feature in the live window", labels=["feature"])
        reference_mean = GaugeMetricFamily("student_dropout_feature_reference_mean",
                                           "Mean of a numeric feature in the reference profile", labels=["feature"])
        missing = GaugeMetricFamily("student_dropout_feature_window_missing_rate",
                                    "Share of null values per feature in the live window", labels=["feature"])
        drifted = GaugeMetricFamily("student_dropout_drifted_features",
                                    "Features currently in each drift state", labels=["severity"])
        severity = Counter(d["status"] for d in drift)
        for d in drift:
            score.add_metric([d["feature"], d["metric"]], d["value"])
            status.add_metric([d["feature"]], STATUS_CODES[d["status"]])
            missing.add_metric([d["feature"]], d["window_missing_rate"])
            if d["window_mean"] is not None and not math.isnan(d["window_mean"]):
                window_mean.add_metric([d["feature"]], d["window_mean"])
            if d["reference_mean"] is not None:
                reference_mean.add_metric([d["feature"]], d["reference_mean"])
        if drift:
            drifted.add_metric(["moderate"], severity.get("moderate drift", 0))
            drifted.add_metric(["substantial"], severity.get("substantial drift", 0))
        yield from (score, status, window_mean, reference_mean, missing, drifted)
