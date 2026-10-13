"""Offline evaluation results (reports/) shaped for the web UI."""
from fastapi import APIRouter

from src.api.feature_catalog import transformed_label
from src.api.inference import inference_service
from src.api.telemetry import report_store

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])


@router.get("/models")
def models():
    return {
        "comparison": report_store.model_comparison(),
        "calibration": report_store.calibration(),
        "calibration_audit": report_store.calibration_audit(),
        "risk_threshold_sweep": report_store.risk_threshold_sweep(),
        "selective_threshold_sweep": report_store.selective_threshold_sweep(),
        "integrated_summary": report_store.integrated_summary(),
    }


@router.get("/explainability")
def explainability():
    shap = [dict(row, label=transformed_label(row["feature"])) for row in report_store.shap_importance()]
    gain = [dict(row, label=transformed_label(row["feature"])) for row in report_store.gain_importance()]
    return {"shap": shap, "gain": gain}


@router.get("/fairness")
def fairness():
    return {
        "disparity": report_store.fairness_disparity(),
        "groups": report_store.group_metrics(),
        "mitigation": report_store.mitigation(),
        "compatibility": report_store.fairness_compatibility(),
    }


@router.get("/interventions")
def interventions():
    engine = inference_service.intervention_engine
    return {
        "tiers": report_store.risk_tier_validation(),
        "mapping": report_store.intervention_mapping(),
        "thresholds": engine.tier_mapper.config if engine else None,
    }


@router.get("/pipeline")
def pipeline():
    return {"runs": report_store.pipeline_runs()}
