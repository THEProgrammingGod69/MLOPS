# Student Dropout Early Warning · MLOps

Fairness-aware early-warning system that predicts, at **day 28** of an Open University
module (OULAD), which students are likely to withdraw, maps each score to a risk tier and
intervention, explains it with SHAP, and runs in production with live monitoring.

| Layer | What it is | Where |
|---|---|---|
| Data & training | DVC-versioned OULAD pipeline, baselines, calibration, fairness mitigation, MLflow | `src/data`, `src/models`, `src/fairness`, `src/calibration`, `src/pipeline` |
| Inference API | FastAPI: legacy `/predict` + versioned `/api/v1` (single, batch, insights, monitoring) | `src/api` |
| Web UI | React + TypeScript console: risk assessment, batch scoring, model insights, fairness, live monitoring | `frontend/` |
| Observability | Prometheus metrics (live + offline), drift monitor, 9 alert rules, 66-panel Grafana dashboard | `src/monitoring`, `monitoring/` |

## Quick start (Docker, everything)

```bash
# the served model must exist locally first (dvc pull, or run the training pipeline)
ls models/baseline/xgb_pipeline.pkl

docker compose up -d --build                  # API, web UI, Prometheus, Grafana
docker compose --profile demo up -d --build   # same, plus a synthetic traffic generator
```

| Service | URL |
|---|---|
| Web UI | http://localhost:8080 |
| API docs (Swagger) | http://localhost:8000/docs |
| Grafana (anonymous viewer, admin/admin) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

## Local development

```bash
pip install -r requirements-api.txt
uvicorn src.api.main:app --reload --port 8000           # API

cd frontend && npm install && npm run dev                # UI on http://localhost:5173 (proxies /api)

docker compose -f docker-compose.monitoring.yml up -d    # Prometheus + Grafana scraping the host API
python scripts/simulate_traffic.py --rps 5               # optional: live traffic for the dashboards
```

Single-process alternative: `cd frontend && npm run build`, then the API also serves the UI at
http://localhost:8000/ui/.

For exact drift monitoring on all 21 features, build the reference profile from the training
split once: `python -m src.monitoring.build_reference_profile`.

## Tests

```bash
python -m unittest discover -s tests -v     # backend, monitoring, dashboard and alert checks
cd frontend && npm run build                # type-check + production build of the UI
```

## Documentation

* **[docs/web_platform_and_observability.md](docs/web_platform_and_observability.md)**: reference for the web UI, the v1 API, live drift monitoring, the Grafana dashboard and alerting (start here)
* `docs/api_deployment.md`, `docs/monitoring_and_drift.md`: original deployment and monitoring notes
* `docs/` also covers the data pipeline, modelling, calibration, fairness and explainability steps
