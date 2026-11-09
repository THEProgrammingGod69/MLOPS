# Student Dropout Early Warning · MLOps

Fairness-aware early-warning system that predicts, at **day 28** of an Open University
module (OULAD), which students are likely to withdraw, maps each score to a risk tier and
intervention, explains it with SHAP, and runs in production with live monitoring.

| Layer | What it is | Where |
|---|---|---|
| Data & training | DVC-versioned OULAD pipeline, baselines, calibration, fairness mitigation, MLflow | `src/data`, `src/models`, `src/fairness`, `src/calibration`, `src/pipeline` |
| Inference API | FastAPI: legacy `/predict` + versioned `/api/v1` (single, batch, insights, monitoring) | `src/api` |
| Web UI | "The Early Warning" broadsheet: alert desk, case file, institution intake, cohort lab, model insights, fairness, observatory | `frontend/` |
| Observability | Prometheus metrics (live + offline), drift monitor, 11 alert rules, 83-panel Grafana dashboard | `src/monitoring`, `monitoring/` |
| Alert desk | Every student at or above 50 % opens a case and fires `StudentDropoutRiskAbove50` in Grafana | `src/api/alert_desk.py` |
| Institution adapter | Fits any institution's CSV/Excel/JSON to the model's 21 inputs and discloses how far to trust it | `src/adapter` |
| Decision lab | Rescue plans, advisor triage and cohort stress tests | `src/api/lab.py` |

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

## Public deployment (Render)

`render.yaml` deploys the API + web UI, Prometheus and Grafana as three public HTTPS services:
commit the model files (see `models/README.md`), then on render.com choose **New → Blueprint**
and select this repository. Details and free-tier caveats:
[docs/web_platform_and_observability.md §3.2](docs/web_platform_and_observability.md).

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

## Model provenance

The deployed model is the project's XGBoost pipeline trained on the real
[Open University Learning Analytics Dataset](https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset)
(Kuzilek, Hlosta and Zdrahal, *Scientific Data* 4:170171, 2017, CC BY 4.0), with a checksum matching
this repository's DVC record. Retraining with `scripts/train_served_model.py` reproduces the committed
report: validation ROC-AUC 0.723 (report 0.721), PR-AUC 0.393 (report 0.390).

At the 50 % alert line it flags 3.5 % of validation students, with 57 % precision and 11 % recall. So the
alert line is a high-confidence signal, and most eventual withdrawals sit in the HIGH and MODERATE tiers.

## Documentation

* **[docs/web_platform_and_observability.md](docs/web_platform_and_observability.md)**: reference for the web UI, the v1 API, live drift monitoring, the Grafana dashboard and alerting (start here)
* **[docs/alerts_adapter_and_lab.md](docs/alerts_adapter_and_lab.md)**: 50 % alerts, the institution data adapter, the decision lab and cold-start behaviour
* `docs/api_deployment.md`, `docs/monitoring_and_drift.md`: original deployment and monitoring notes
* `docs/` also covers the data pipeline, modelling, calibration, fairness and explainability steps
