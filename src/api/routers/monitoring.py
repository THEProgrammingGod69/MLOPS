"""Live monitoring views computed from the in-process rolling window."""
from fastapi import APIRouter, Query

from src.api.inference import inference_service
from src.api.telemetry import live_monitor

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("/summary")
def summary():
    data = live_monitor.summary()
    data["model_version"] = inference_service.model_version
    return data


@router.get("/drift")
def drift():
    profile = live_monitor.profile or {}
    features = live_monitor.drift()
    return {
        "ready": bool(features),
        "window_size": live_monitor.window_stats()["size"],
        "window_capacity": live_monitor.window_size,
        "min_samples": live_monitor.min_samples,
        "min_samples_categorical": live_monitor.min_samples_categorical,
        "thresholds": {"psi": live_monitor.psi_thresholds, "tvd": live_monitor.tvd_thresholds},
        "reference": {k: profile.get(k) for k in ("source", "approximate", "generated_at", "n_rows", "note")},
        "features": features,
    }


@router.get("/recent")
def recent(limit: int = Query(50, ge=1, le=200)):
    return {"items": live_monitor.recent(limit)}
