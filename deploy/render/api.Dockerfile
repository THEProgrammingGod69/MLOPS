# Render free web service 1 of 2: FastAPI + web UI (one 512 MB instance).
# Also carries an hour of recorded monitoring history, which the monitoring service downloads
# from /api/v1/replay at boot so its charts are never empty after Render puts it to sleep.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
RUN python -c "import pathlib, shap; p = pathlib.Path(shap.__file__).parent / 'explainers' / '_tree.py'; s = p.read_text(encoding='utf-8'); old = 'float(learner_model_param[\"base_score\"])'; p.write_text(s.replace(old, 'float(str(learner_model_param[\"base_score\"]).strip(\"[]\"))'), encoding='utf-8')"
COPY configs/ configs/
COPY src/ src/
COPY reports/ reports/
COPY scripts/ scripts/
COPY deploy/vercel/record_history.py deploy/vercel/seed_traffic.py deploy/vercel/
COPY deploy/render/api-start.sh deploy/render/
COPY --from=ui /ui/dist frontend/dist
COPY models/ models/
# A model that cannot load must fail the build, leaving the running service in place.
RUN python -c "from src.api.inference import inference_service as s; assert s.loaded and s.to_pipeline is not None and s.explainer is not None, s.components; print(s.components)"
RUN python deploy/vercel/record_history.py && chmod -R a+rX /opt/replay
ENV DEMO_TRAFFIC_RPS=1 PORT=10000
CMD ["sh", "deploy/render/api-start.sh"]
