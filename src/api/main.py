"""FastAPI application: legacy inference contract + /api/v1 for the web UI.

Endpoints
---------
Legacy (unchanged contract, used by tests, Prometheus and existing clients):
    GET  /            service banner
    GET  /health      model health
    GET  /metrics     Prometheus exposition
    POST /predict     single prediction (optional SHAP via ?include_explanation=true)

Versioned (web UI and integrations), see ``src/api/routers``:
    /api/v1/health, /meta, /model, /schema
    /api/v1/predict, /api/v1/predict/batch
    /api/v1/insights/{models,explainability,fairness,interventions,pipeline}
    /api/v1/monitoring/{summary,drift,recent}

When ``frontend/dist`` exists (``npm run build``) the web UI is also served at /ui/.
"""
import logging
import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.inference import inference_service
from src.api.routers import insights, monitoring, predict as predict_v1, system
from src.api.schemas import HealthResponse, PredictionResponse, PredictiveFeatures
from src.api.settings import SERVICE_NAME, SERVICE_VERSION, settings
from src.api.telemetry import record_error, record_predictions
from src.monitoring.application_metrics import (HTTP_IN_PROGRESS, HTTP_LATENCY, HTTP_REQUESTS,
                                                PREDICTION_LATENCY, PREDICTION_REQUESTS,
                                                metrics_endpoint)

# Setup minimal safe logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UI_PREFIX = "/ui"
UNTRACKED_PATHS = {"/metrics"}  # Prometheus' own scrapes would drown the traffic panels

app = FastAPI(
    title=SERVICE_NAME,
    version=SERVICE_VERSION,
    description="Inference API for predicting student dropout risk and providing interventions.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    if request.url.path.startswith(UI_PREFIX):
        return UI_PREFIX
    return "unmatched"


@app.middleware("http")
async def add_process_time_header(request, call_next):
    path = request.url.path
    if path in UNTRACKED_PATHS:
        return await call_next(request)
    start_time = time.time()
    HTTP_IN_PROGRESS.inc()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        HTTP_IN_PROGRESS.dec()
        process_time = time.time() - start_time
        route = _route_label(request)
        HTTP_REQUESTS.labels(method=request.method, route=route, status=str(status_code)).inc()
        HTTP_LATENCY.labels(method=request.method, route=route).observe(process_time)
        # Minimal safe logging (no full payload, sensitive data, or PII)
        if route != UI_PREFIX:
            logger.info(f"Method: {request.method} Path: {path} Status: {status_code} Latency: {process_time:.4f}s")


@app.get("/")
def read_root(request: Request):
    # Browsers land on the web UI; API clients (and the original contract) get the JSON banner.
    if os.path.isdir(settings.ui_dist_dir) and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url=f"{UI_PREFIX}/")
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status": "running",
        "docs": "/docs",
        "ui": f"{UI_PREFIX}/" if os.path.isdir(settings.ui_dist_dir) else None,
    }


@app.get("/health", response_model=HealthResponse)
def health_check():
    loaded = inference_service.is_healthy()
    status = "healthy" if loaded else "unhealthy"
    return HealthResponse(status=status, model_loaded=loaded)


@app.get("/metrics")
def get_metrics(request: Request):
    return metrics_endpoint(request)


@app.post("/predict", response_model=PredictionResponse)
def predict(features: PredictiveFeatures, include_explanation: bool = False):
    PREDICTION_REQUESTS.inc()
    start_time = time.time()
    try:
        result = inference_service.score([features], include_explanation=include_explanation)[0]
    except HTTPException:
        record_error()
        raise
    except Exception as e:
        record_error()
        logger.error(f"Prediction failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Inference failed due to an internal error")
    elapsed = time.time() - start_time
    PREDICTION_LATENCY.observe(elapsed)
    record_predictions([result], source="single", latency_seconds=elapsed)
    return PredictionResponse(**{k: result[k] for k in PredictionResponse.model_fields})


app.include_router(system.router)
app.include_router(predict_v1.router)
app.include_router(insights.router)
app.include_router(monitoring.router)

if os.path.isdir(settings.ui_dist_dir):
    @app.get(UI_PREFIX, include_in_schema=False)
    def ui_redirect():
        return RedirectResponse(url=f"{UI_PREFIX}/")

    app.mount(UI_PREFIX, StaticFiles(directory=settings.ui_dist_dir, html=True), name="ui")
