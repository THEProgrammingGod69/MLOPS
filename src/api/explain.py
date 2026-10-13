"""SHAP explanations for the served XGBoost pipeline.

Two interchangeable backends compute the same quantity, path-dependent TreeSHAP
values in log-odds space:

* ``shap.TreeExplainer`` through the project's ``SHAPExplainer`` (Step 2.10).
* XGBoost's native ``pred_contribs=True``, the TreeSHAP implementation built into
  the booster.

The shap library is preferred. Releases up to 0.49 cannot parse the ``base_score``
that XGBoost >= 3 writes (``"[5E-1]"``); the Dockerfile patches that, but a plain
``pip install`` does not. Rather than taking predictions down with it, the engine
falls back to the native backend and reports which one is active.
"""
import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from src.api.feature_catalog import base_feature
from src.models.train_baselines import PREDICTIVE_FEATURES

logger = logging.getLogger(__name__)

SHAP_BACKEND = "shap.TreeExplainer"
NATIVE_BACKEND = "xgboost.pred_contribs"


class ExplanationEngine:
    def __init__(self, pipeline, model_path: str, prefer_shap: bool = True):
        self.preprocessor = pipeline.named_steps["preprocessor"]
        self.classifier = pipeline.named_steps["classifier"]
        self.feature_names: List[str] = list(self.preprocessor.get_feature_names_out())
        self.fallback_reason = None
        self._shap_explainer = None

        if prefer_shap:
            try:
                from src.explainability.shap_explainer import SHAPExplainer
                self._shap_explainer = SHAPExplainer(model_path=model_path)
            except Exception as exc:  # incompatible shap/xgboost pair, missing package, ...
                self.fallback_reason = f"{type(exc).__name__}: {exc}"
                logger.warning("shap.TreeExplainer unavailable, using XGBoost native TreeSHAP (%s)",
                               self.fallback_reason)
        self.backend = SHAP_BACKEND if self._shap_explainer is not None else NATIVE_BACKEND

        # Map every transformed column to the raw feature it came from.
        self._column_to_feature = [base_feature(name) for name in self.feature_names]

    def _native(self, X_raw: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        import xgboost as xgb

        X_proc = self.preprocessor.transform(X_raw)
        booster = self.classifier.get_booster()
        missing = self.classifier.missing if self.classifier.missing is not None else np.nan
        dmatrix = xgb.DMatrix(X_proc, missing=missing, feature_names=booster.feature_names)
        contribs = booster.predict(dmatrix, pred_contribs=True)
        return contribs[:, :-1], contribs[:, -1]

    def _shap(self, X_raw: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        values, _ = self._shap_explainer.explain_instances(X_raw)
        values = np.asarray(values)
        expected = np.asarray(self._shap_explainer.explainer.expected_value, dtype=float).ravel()
        base = np.full(values.shape[0], float(expected[-1]))
        return values, base

    def explain(self, X_raw: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Return (contributions[n_rows, n_transformed_columns], base_values[n_rows])."""
        if self._shap_explainer is not None:
            return self._shap(X_raw)
        return self._native(X_raw)

    def aggregate(self, contributions_row: np.ndarray) -> Dict[str, float]:
        """Sum one row's transformed-column contributions per raw input feature."""
        totals = {feature: 0.0 for feature in PREDICTIVE_FEATURES}
        for feature, value in zip(self._column_to_feature, contributions_row):
            if feature is not None:
                totals[feature] += float(value)
        return totals
