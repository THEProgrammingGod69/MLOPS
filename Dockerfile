# deploy/vercel branch: ALL-IN-ONE public demo image (one port).
#   /            web UI + FastAPI (+ built-in demo traffic)
#   /grafana/    Grafana (anonymous viewer, provisioned 66-panel dashboard)
#   /prometheus/ Prometheus (scrapes the API, evaluates the 9 alert rules)
# The model is a schema-faithful DEMO stand-in trained at build time
# (deploy/vercel/make_demo_model.py): the real OULAD artifacts are not in git.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends nginx curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/prometheus /opt/grafana \
 && curl -fsSL https://github.com/prometheus/prometheus/releases/download/v2.53.2/prometheus-2.53.2.linux-amd64.tar.gz \
    | tar xz --strip-components=1 -C /opt/prometheus \
 && curl -fsSL https://dl.grafana.com/oss/release/grafana-11.2.2.linux-amd64.tar.gz \
    | tar xz --strip-components=1 -C /opt/grafana
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
RUN python -c "import pathlib, shap; p = pathlib.Path(shap.__file__).parent / 'explainers' / '_tree.py'; s = p.read_text(encoding='utf-8'); old = 'float(learner_model_param[\"base_score\"])'; p.write_text(s.replace(old, 'float(str(learner_model_param[\"base_score\"]).strip(\"[]\"))'), encoding='utf-8')"
COPY configs/ configs/
COPY src/ src/
COPY reports/ reports/
COPY scripts/ scripts/
COPY deploy/vercel/ deploy/vercel/
COPY --from=ui /ui/dist frontend/dist
RUN python deploy/vercel/make_demo_model.py

# Monitoring configuration, rewritten for the single-host layout
COPY monitoring/ /opt/monitoring-src/
RUN mkdir -p /opt/monitoring/provisioning \
 && sed -e 's#api:8000#127.0.0.1:8000#' -e 's#/etc/prometheus/alerts.yml#/opt/monitoring-src/prometheus/alerts.yml#' \
        -e 's#environment: "docker"#environment: "vercel"#' \
        /opt/monitoring-src/prometheus/prometheus.docker.yml > /opt/monitoring/prometheus.yml \
 && cp -r /opt/monitoring-src/grafana/provisioning/* /opt/monitoring/provisioning/ \
 && sed -i 's#http://prometheus:9090#http://127.0.0.1:9090/prometheus#' /opt/monitoring/provisioning/datasources/prometheus.yml \
 && sed -i 's#/var/lib/grafana/dashboards#/opt/monitoring-src/grafana/dashboards#' /opt/monitoring/provisioning/dashboards/dashboards.yml \
 && /opt/prometheus/promtool check config /opt/monitoring/prometheus.yml

ENV GRAFANA_URL=/grafana PROMETHEUS_URL=/prometheus \
    DEMO_TRAFFIC_RPS=3 SIM_SCHEDULE=normal:900,engagement-drop:600 \
    GF_PATHS_PROVISIONING=/opt/monitoring/provisioning \
    GF_SERVER_HTTP_ADDR=127.0.0.1 GF_SERVER_HTTP_PORT=3300 \
    GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s/grafana/ GF_SERVER_SERVE_FROM_SUB_PATH=true \
    GF_AUTH_ANONYMOUS_ENABLED=true GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer GF_AUTH_DISABLE_LOGIN_FORM=true \
    GF_USERS_DEFAULT_THEME=dark GF_USERS_ALLOW_SIGN_UP=false \
    GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/opt/monitoring-src/grafana/dashboards/prediction_dashboard.json \
    GF_ANALYTICS_REPORTING_ENABLED=false GF_ANALYTICS_CHECK_FOR_UPDATES=false \
    GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES=false GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED=true \
    GF_NEWS_NEWS_FEED_ENABLED=false GF_LIVE_MAX_CONNECTIONS=0 \
    GF_DASHBOARDS_MIN_REFRESH_INTERVAL=10s PORT=8080
# Run Grafana's schema migrations and provisioning once at build time (copied to /tmp at boot).
RUN mkdir -p /opt/grafana-seed /tmp/gl /tmp/gp \
 && GF_PATHS_DATA=/opt/grafana-seed GF_PATHS_LOGS=/tmp/gl GF_PATHS_PLUGINS=/tmp/gp \
    /opt/grafana/bin/grafana server --homepath /opt/grafana > /tmp/grafana-build.log 2>&1 & GPID=$! \
 ; for i in $(seq 1 120); do curl -fs http://127.0.0.1:3300/grafana/api/health >/dev/null && break; sleep 1; done \
 ; curl -fs http://127.0.0.1:3300/grafana/api/search | grep -q mlops-monitoring || { tail -40 /tmp/grafana-build.log; exit 1; } \
 ; kill $GPID; sleep 2; ls -la /opt/grafana-seed
EXPOSE 8080
CMD ["sh", "deploy/vercel/start-all.sh"]
