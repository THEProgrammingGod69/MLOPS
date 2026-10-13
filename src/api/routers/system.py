"""Service, model and schema metadata."""
import time

from fastapi import APIRouter

from src.api.feature_catalog import schema_payload
from src.api.inference import inference_service
from src.api.settings import SERVICE_NAME, SERVICE_VERSION, settings
from src.api.telemetry import live_monitor, report_store

router = APIRouter(prefix="/api/v1", tags=["system"])
DEPLOYED_MODEL = "xgb"


@router.get("/health")
def health():
    healthy = inference_service.is_healthy()
    return {
        "status": "healthy" if healthy else "unhealthy",
        "model_loaded": healthy,
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "model_version": inference_service.model_version,
        "uptime_seconds": round(time.time() - live_monitor.started_at, 1),
        "components": inference_service.components,
    }


@router.get("/meta")
def meta():
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "links": {"grafana": settings.grafana_url, "prometheus": settings.prometheus_url,
                  "api_docs": "/docs", "metrics": "/metrics"},
    }


@router.get("/model")
def model_card():
    card = inference_service.model_card()
    engine = inference_service.intervention_engine
    card["risk_tiers"] = engine.tier_mapper.config if engine else None
    card["intervention_rules"] = engine.rule_engine.config if engine else None
    offline = {}
    for row in report_store.model_comparison():
        if row["model"] == DEPLOYED_MODEL:
            offline.setdefault(row["split"], {})[row["metric"]] = row["value"]
    card["offline_metrics"] = offline
    card["deployed_model_key"] = DEPLOYED_MODEL
    return card


@router.get("/schema")
def schema():
    return schema_payload()
