FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy dependency list
COPY requirements-api.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements-api.txt

# SHAP 0.49.1 + XGBoost >=2.1 compatibility patch for base_score JSON string parsing.
# (The previous multi-line version was a Python SyntaxError: line continuations joined
# "with" statements onto one line.) Without the patch the API falls back to XGBoost's
# native TreeSHAP, which returns identical values.
RUN python -c "import pathlib, shap; p = pathlib.Path(shap.__file__).parent / 'explainers' / '_tree.py'; s = p.read_text(encoding='utf-8'); old = 'float(learner_model_param[\"base_score\"])'; p.write_text(s.replace(old, 'float(str(learner_model_param[\"base_score\"]).strip(\"[]\"))'), encoding='utf-8'); print('shap base_score patch applied to', s.count(old), 'location(s)')"

# Application code, configuration (incl. the drift reference profile) and the offline
# evaluation reports that feed /api/v1/insights and the Grafana offline-metrics panels.
COPY configs/ configs/
COPY src/ src/
COPY reports/ reports/

# Model artifacts: .dockerignore keeps only the served XGBoost pipeline and the
# fairness post-processor (if present) from models/.
COPY models/ models/

# Non-root user setup for security
RUN useradd -m apiuser && chown -R apiuser:apiuser /app
USER apiuser

# Expose port and start FastAPI server
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
