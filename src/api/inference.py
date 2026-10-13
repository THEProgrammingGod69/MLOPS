"""Model serving: loads the risk pipeline and its companions, scores students.

Components load independently so one optional failure cannot take the service
down: the risk pipeline and intervention engine are required; the fairness
post-processor (ThresholdOptimizer) and the SHAP explainer are optional and
report their own status. ``score`` is vectorised, so one call serves a single
student, the legacy ``/predict`` contract and batch scoring alike.
"""
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Sequence

import joblib
import numpy as np
import pandas as pd
from fastapi import HTTPException

from src.api.explain import ExplanationEngine
from src.api.feature_catalog import CATEGORICAL_FEATURES, feature_label
from src.api.schemas import PredictiveFeatures, PredictionResponse, SHAPExplanation
from src.api.settings import settings
from src.intervention.intervention_engine import InterventionEngine
from src.models.train_baselines import PREDICTIVE_FEATURES

logger = logging.getLogger(__name__)

NUMERIC_FEATURES = [c for c in PREDICTIVE_FEATURES if c not in CATEGORICAL_FEATURES]
SUPPORTED_GENDERS = ("M", "F")
FAIRNESS_RANDOM_STATE = 42  # ThresholdOptimizer.predict is randomised; fix it for reproducible decisions
FAIRNESS_UNAVAILABLE = "Unavailable: gender missing or mitigation model missing"


def _file_metadata(path: str) -> dict:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    stat = os.stat(path)
    return {
        "path": path.replace("\\", "/"),
        "sha256": digest.hexdigest(),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
    }


class InferenceService:
    def __init__(self, model_path: Optional[str] = None, to_path: Optional[str] = None,
                 intervention_config_path: Optional[str] = None, prefer_shap: bool = True):
        self.model_path = model_path or settings.model_path
        self.to_path = to_path or settings.mitigation_model_path
        self.intervention_config_path = intervention_config_path or settings.intervention_config_path
        self.pipeline = None
        self.to_pipeline = None
        self.intervention_engine = None
        self.explainer: Optional[ExplanationEngine] = None
        self.artifact: Optional[dict] = None
        self.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.components = {name: {"loaded": False, "detail": None}
                           for name in ("model", "intervention_engine", "fairness_mitigator", "explainer")}
        self._load(prefer_shap)

    # -- loading ------------------------------------------------------------------------
    def _set(self, component: str, loaded: bool, detail: Optional[str] = None) -> None:
        self.components[component] = {"loaded": loaded, "detail": detail}

    def _load(self, prefer_shap: bool) -> None:
        try:
            self.pipeline = joblib.load(self.model_path)
            self.artifact = _file_metadata(self.model_path)
            self._set("model", True, type(self.pipeline.named_steps["classifier"]).__name__)
        except Exception as exc:
            self.pipeline = None
            self._set("model", False, f"{type(exc).__name__}: {exc}")
            logger.error("Failed to load risk model from %s: %s", self.model_path, exc)

        try:
            self.intervention_engine = InterventionEngine(self.intervention_config_path)
            self._set("intervention_engine", True, self.intervention_config_path)
        except Exception as exc:
            self._set("intervention_engine", False, f"{type(exc).__name__}: {exc}")
            logger.error("Failed to load intervention rules: %s", exc)

        if os.path.exists(self.to_path):
            try:
                self.to_pipeline = joblib.load(self.to_path)
                self._set("fairness_mitigator", True, "ThresholdOptimizer (equalized odds, gender)")
            except Exception as exc:
                self._set("fairness_mitigator", False, f"{type(exc).__name__}: {exc}")
                logger.warning("Fairness mitigation model present but not loadable: %s", exc)
        else:
            self._set("fairness_mitigator", False, f"Artifact not found: {self.to_path}")

        if self.pipeline is not None:
            try:
                self.explainer = ExplanationEngine(self.pipeline, self.model_path, prefer_shap=prefer_shap)
                self._set("explainer", True, self.explainer.backend)
            except Exception as exc:
                self._set("explainer", False, f"{type(exc).__name__}: {exc}")
                logger.warning("Explanations unavailable: %s", exc)

    def reload(self, model_path: Optional[str] = None, to_path: Optional[str] = None,
               prefer_shap: bool = True) -> None:
        """Reload artifacts in place (every router holds a reference to this one instance)."""
        self.__init__(model_path or self.model_path, to_path or self.to_path,
                      self.intervention_config_path, prefer_shap=prefer_shap)

    # -- status -----------------------------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self.pipeline is not None and self.intervention_engine is not None

    def is_healthy(self) -> bool:
        return self.loaded

    @property
    def model_version(self) -> str:
        return self.artifact["sha256"][:12] if self.artifact else "unavailable"

    def model_card(self) -> dict:
        card = {"loaded": self.loaded, "version": self.model_version, "artifact": self.artifact,
                "loaded_at": self.loaded_at, "components": self.components,
                "n_raw_features": len(PREDICTIVE_FEATURES), "n_transformed_features": None,
                "estimator": None, "hyperparameters": {}}
        if self.pipeline is not None:
            classifier = self.pipeline.named_steps["classifier"]
            params = classifier.get_params()
            card["estimator"] = type(classifier).__name__
            card["hyperparameters"] = {k: params.get(k) for k in (
                "n_estimators", "max_depth", "learning_rate", "subsample", "colsample_bytree",
                "eval_metric", "random_state") if params.get(k) is not None}
            if self.explainer is not None:
                card["n_transformed_features"] = len(self.explainer.feature_names)
        return card

    # -- scoring ----------------------------------------------------------------------------
    @staticmethod
    def to_frame(features: Sequence[PredictiveFeatures]) -> pd.DataFrame:
        df = pd.DataFrame([{key: getattr(f, key) for key in PREDICTIVE_FEATURES} for f in features],
                          columns=PREDICTIVE_FEATURES)
        for column in NUMERIC_FEATURES:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        return df

    def _fairness(self, df: pd.DataFrame, genders: List[Optional[str]]):
        decisions: List[Optional[int]] = [None] * len(df)
        statuses: List[str] = [FAIRNESS_UNAVAILABLE] * len(df)
        if self.to_pipeline is None:
            return decisions, statuses
        eligible = []
        for i, gender in enumerate(genders):
            if not gender:
                continue
            if gender not in SUPPORTED_GENDERS:
                statuses[i] = f"Unavailable: unsupported gender '{gender}'"
            else:
                eligible.append(i)
        if eligible:
            try:
                subset = df.iloc[eligible].reset_index(drop=True)
                sensitive = pd.Series([genders[i] for i in eligible])
                predicted = self.to_pipeline.predict(subset, sensitive_features=sensitive,
                                                     random_state=FAIRNESS_RANDOM_STATE)
                for i, decision in zip(eligible, predicted):
                    decisions[i] = int(decision)
                    statuses[i] = "Applied"
            except Exception as exc:
                for i in eligible:
                    statuses[i] = f"Unavailable: {exc}"
        return decisions, statuses

    def score(self, features: Sequence[PredictiveFeatures], include_explanation: bool = False) -> List[dict]:
        """Score students. Returns one plain dict per student (superset of every response schema)."""
        if not self.loaded:
            raise HTTPException(status_code=503, detail="Model is not loaded")
        if include_explanation and self.explainer is None:
            raise HTTPException(status_code=503, detail="Explanation engine is not available")

        df = self.to_frame(features)
        try:
            probabilities = self.pipeline.predict_proba(df)[:, 1]
        except Exception as exc:
            logger.error("Inference failed: %s", exc)
            raise HTTPException(status_code=500, detail="Inference failed due to an internal error")

        decisions, statuses = self._fairness(df, [getattr(f, "gender", None) for f in features])

        contributions = base_values = None
        explanation_seconds = 0.0
        if include_explanation:
            started = time.perf_counter()
            try:
                contributions, base_values = self.explainer.explain(df)
            except Exception as exc:
                logger.error("SHAP explanation failed: %s", exc)
                raise HTTPException(status_code=500, detail="Failed to generate SHAP explanation")
            explanation_seconds = time.perf_counter() - started

        results = []
        raw_rows = df.to_dict(orient="records")
        for i, probability in enumerate(probabilities):
            probability = float(probability)
            recommendation = self.intervention_engine.generate_recommendation(probability)
            raw = {k: getattr(features[i], k) for k in PREDICTIVE_FEATURES}
            result = {
                "prediction_id": uuid.uuid4().hex[:16],
                "risk_probability": probability,
                "risk_tier": recommendation["risk_tier"],
                "priority_score": probability,
                "human_review_required": bool(recommendation["human_review_required"]),
                "intervention_level": recommendation["intervention_level"],
                "recommended_actions": list(recommendation["recommended_actions"]),
                "fairness_adjusted_decision": decisions[i],
                "fairness_status": statuses[i],
                "missing_features": [k for k in PREDICTIVE_FEATURES if pd.isna(raw_rows[i][k])],
                "top_positive_contributors": None,
                "top_negative_contributors": None,
                "explanation": None,
                "top_driver": None,
                "inputs": raw,
                "explanation_seconds": explanation_seconds / len(probabilities) if include_explanation else 0.0,
            }
            if contributions is not None:
                row = contributions[i]
                pairs = list(zip(self.explainer.feature_names, (float(v) for v in row)))
                positive = sorted([p for p in pairs if p[1] > 0], key=lambda p: p[1], reverse=True)[:5]
                negative = sorted([p for p in pairs if p[1] < 0], key=lambda p: p[1])[:5]
                result["top_positive_contributors"] = [
                    SHAPExplanation(feature=f, contribution=v, direction="Positive") for f, v in positive]
                result["top_negative_contributors"] = [
                    SHAPExplanation(feature=f, contribution=v, direction="Negative") for f, v in negative]
                aggregated = self.explainer.aggregate(row)
                ranked = sorted(aggregated.items(), key=lambda kv: abs(kv[1]), reverse=True)
                result["explanation"] = {
                    "backend": self.explainer.backend,
                    "base_value": float(base_values[i]),
                    "contributions": [{"feature": f, "label": feature_label(f), "value": raw[f],
                                       "contribution": c} for f, c in ranked],
                }
                top = max(aggregated.items(), key=lambda kv: kv[1])
                result["top_driver"] = feature_label(top[0]) if top[1] > 0 else None
            results.append(result)

        return results

    def predict(self, features: PredictiveFeatures, include_explanation: bool = False) -> PredictionResponse:
        """Legacy single-student contract used by ``POST /predict``."""
        result = self.score([features], include_explanation=include_explanation)[0]
        return PredictionResponse(**{k: result[k] for k in PredictionResponse.model_fields})


def fairness_metric_status(status: str) -> str:
    """Bounded label for the fairness_decisions metric."""
    if status == "Applied":
        return "applied"
    if status == FAIRNESS_UNAVAILABLE:
        return "not_requested_or_unavailable"
    if status.startswith("Unavailable: unsupported gender"):
        return "unsupported_gender"
    return "error"


# Global singleton instance
inference_service = InferenceService()
