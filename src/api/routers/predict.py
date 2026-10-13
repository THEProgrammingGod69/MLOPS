"""Single and batch scoring for the web UI (/api/v1/predict*)."""
import statistics
import time

from fastapi import APIRouter, HTTPException

from src.api.inference import inference_service
from src.api.schemas import (BatchPredictionRequest, BatchPredictionResponse, PredictiveFeatures,
                             PredictionResponseV1)
from src.api.settings import settings
from src.api.telemetry import record_error, record_predictions
from src.monitoring import application_metrics as m

router = APIRouter(prefix="/api/v1", tags=["prediction"])
TOP_DRIVERS_PER_ROW = 3


def _v1_payload(result: dict, latency_ms: float) -> dict:
    payload = {k: result[k] for k in PredictionResponseV1.model_fields if k in result}
    payload.update(model_version=inference_service.model_version, latency_ms=round(latency_ms, 3))
    return payload


@router.post("/predict", response_model=PredictionResponseV1)
def predict(features: PredictiveFeatures, include_explanation: bool = True):
    m.PREDICTION_REQUESTS.inc()
    started = time.perf_counter()
    try:
        result = inference_service.score([features], include_explanation=include_explanation)[0]
    except Exception as exc:
        record_error()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Inference failed due to an internal error")
    elapsed = time.perf_counter() - started
    m.PREDICTION_LATENCY.observe(elapsed)
    record_predictions([result], source="single", latency_seconds=elapsed)
    return _v1_payload(result, elapsed * 1000)


@router.post("/predict/batch", response_model=BatchPredictionResponse)
def predict_batch(request: BatchPredictionRequest):
    if len(request.students) > settings.max_batch_size:
        raise HTTPException(status_code=413,
                            detail=f"Batch of {len(request.students)} exceeds the limit of {settings.max_batch_size}")
    m.PREDICTION_REQUESTS.inc()
    m.BATCH_REQUESTS.inc()
    started = time.perf_counter()
    try:
        results = inference_service.score(request.students, include_explanation=request.include_explanation)
    except Exception as exc:
        record_error()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Inference failed due to an internal error")
    elapsed = time.perf_counter() - started
    m.BATCH_SIZE.observe(len(results))
    m.BATCH_LATENCY.observe(elapsed)
    record_predictions(results, source="batch")

    rows = []
    for index, (student, result) in enumerate(zip(request.students, results)):
        drivers = None
        if result["explanation"]:
            positive = [c for c in result["explanation"]["contributions"] if c["contribution"] > 0]
            drivers = sorted(positive, key=lambda c: c["contribution"], reverse=True)[:TOP_DRIVERS_PER_ROW]
        rows.append({
            "index": index, "record_id": student.record_id,
            "risk_probability": result["risk_probability"], "risk_tier": result["risk_tier"],
            "intervention_level": result["intervention_level"],
            "human_review_required": result["human_review_required"],
            "fairness_adjusted_decision": result["fairness_adjusted_decision"],
            "fairness_status": result["fairness_status"],
            "missing_features": result["missing_features"], "top_drivers": drivers,
        })

    probabilities = [r["risk_probability"] for r in results]
    review = sum(1 for r in results if r["human_review_required"])
    tier_counts = {tier: 0 for tier in ("LOW", "MODERATE", "HIGH", "CRITICAL")}
    for r in results:
        tier_counts[r["risk_tier"]] = tier_counts.get(r["risk_tier"], 0) + 1
    return {
        "model_version": inference_service.model_version,
        "latency_ms": round(elapsed * 1000, 3),
        "summary": {
            "count": len(results),
            "mean_risk_probability": statistics.fmean(probabilities),
            "median_risk_probability": statistics.median(probabilities),
            "max_risk_probability": max(probabilities),
            "human_review_count": review,
            "human_review_rate": review / len(results),
            "tier_counts": tier_counts,
        },
        "results": rows,
    }
