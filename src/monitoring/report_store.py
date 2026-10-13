"""Read-only access to the offline evaluation reports under ``reports/``.

The batch pipeline (baselines, fairness audit, calibration, interventions, SHAP,
automated pipeline runs) writes CSV/JSON artefacts. This store parses them once,
re-reads a file only when its modification time changes, and hands out JSON-safe
records (NaN -> None). Both the web API (``/api/v1/insights/*``) and the Prometheus
offline-metrics collector read through it, so the UI and Grafana always agree.
"""
import glob
import json
import math
import os
import threading
from typing import Dict, List, Optional

import pandas as pd

MODEL_NAMES = {"lr": "Logistic Regression", "rf": "Random Forest", "xgb": "XGBoost"}
SPLITS = ("train", "validation", "test")
CLASSIFICATION_METRICS = (
    "accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc", "log_loss", "specificity",
)


def _clean(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):  # numpy scalar
        return _clean(value.item())
    return value


def _records(df: pd.DataFrame) -> List[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


class ReportStore:
    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = reports_dir
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    # -- low level ----------------------------------------------------------------
    def _path(self, relative: str) -> str:
        return os.path.join(self.reports_dir, relative)

    def _csv(self, relative: str) -> Optional[pd.DataFrame]:
        path = self._path(relative)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        with self._lock:
            cached = self._cache.get(path)
            if cached and cached[0] == mtime:
                return cached[1]
        try:
            df = pd.read_csv(path)
        except Exception:
            return None
        with self._lock:
            self._cache[path] = (mtime, df)
        return df

    def _rows(self, relative: str) -> List[dict]:
        df = self._csv(relative)
        return [] if df is None else _records(df)

    # -- model quality --------------------------------------------------------------
    def model_comparison(self) -> List[dict]:
        """Long format: one row per (model, split, metric)."""
        df = self._csv("models/baseline_comparison.csv")
        if df is None:
            return []
        rows = []
        for record in _records(df):
            model = record["model"]
            for split in SPLITS:
                for metric in CLASSIFICATION_METRICS:
                    value = record.get(f"{split}_{metric}")
                    if value is not None:
                        rows.append({"model": model, "model_name": MODEL_NAMES.get(model, model),
                                     "split": split, "metric": metric, "value": value})
        return rows

    def calibration(self) -> List[dict]:
        return self._rows("calibration/calibration_summary.csv")

    def calibration_audit(self) -> List[dict]:
        return self._rows("integrated/calibration_audit.csv")

    def risk_threshold_sweep(self) -> List[dict]:
        return self._rows("integrated/risk_threshold_sweep.csv")

    def selective_threshold_sweep(self) -> List[dict]:
        return self._rows("integrated/selective_threshold_sweep.csv")

    def integrated_summary(self) -> List[dict]:
        return self._rows("integrated/integrated_validation_summary.csv")

    # -- explainability ---------------------------------------------------------------
    def shap_importance(self) -> List[dict]:
        return self._rows("explainability/shap_global_importance.csv")

    def gain_importance(self) -> List[dict]:
        return self._rows("models/xgb_feature_importance.csv")

    # -- fairness -------------------------------------------------------------------------
    def fairness_disparity(self) -> List[dict]:
        return self._rows("fairness/disparity_summary.csv")

    def group_metrics(self) -> List[dict]:
        rows = []
        for model in MODEL_NAMES:
            for split in ("validation", "test"):
                rows.extend(self._rows(f"fairness/{model}_{split}_group_metrics.csv"))
        return rows

    def mitigation(self) -> List[dict]:
        validation = [dict(r, split="validation") for r in self._rows("fairness/mitigation_validation_summary.csv")]
        test = [dict(r, split="test") for r in self._rows("fairness/mitigation_test_final.csv")]
        return validation + test

    def fairness_compatibility(self) -> List[dict]:
        return self._rows("integrated/fairness_compatibility.csv")

    # -- interventions --------------------------------------------------------------------
    def risk_tier_validation(self) -> List[dict]:
        return self._rows("intervention/validation_risk_tier_summary.csv")

    def intervention_mapping(self) -> List[dict]:
        return self._rows("intervention/intervention_mapping.csv")

    # -- automated pipeline -----------------------------------------------------------------
    def pipeline_runs(self) -> List[dict]:
        runs = []
        for path in sorted(glob.glob(self._path("pipeline/pipeline_run_*.json"))):
            try:
                with open(path, "r") as f:
                    run = json.load(f)
            except (OSError, ValueError):
                continue
            run["report_file"] = os.path.basename(path)
            runs.append(run)
        runs.sort(key=lambda r: str(r.get("execution_timestamp", "")))
        return runs
