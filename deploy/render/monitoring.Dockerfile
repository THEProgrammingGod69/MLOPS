# Render free web service 2 of 2: Prometheus + Grafana behind nginx (about 200 MB).
#   /grafana/     Grafana (anonymous viewer)
#   /prometheus/  Prometheus, scraping the API service over its public URL
# Boot order (deploy/render/monitoring-start.sh): wake the API, load the recorded hour of
# history, only then start scraping, and open the port last. So a sleeping API never shows
# up as a false "DOWN", and charts are full on first paint.
FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends nginx curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/prometheus /opt/grafana \
 && curl -fsSL https://github.com/prometheus/prometheus/releases/download/v2.53.2/prometheus-2.53.2.linux-amd64.tar.gz \
    | tar xz --strip-components=1 -C /opt/prometheus \
 && curl -fsSL https://dl.grafana.com/oss/release/grafana-11.2.2.linux-amd64.tar.gz \
    | tar xz --strip-components=1 -C /opt/grafana
WORKDIR /app
COPY deploy/vercel/replay_history.py deploy/render/monitoring-start.sh deploy/render/monitoring-nginx.conf.template \
     deploy/render/prometheus.render.yml deploy/render/
COPY monitoring/ /opt/monitoring-src/
RUN mkdir -p /opt/monitoring/provisioning \
 && cp -r /opt/monitoring-src/grafana/provisioning/* /opt/monitoring/provisioning/ \
 && sed -i 's#http://prometheus:9090#http://127.0.0.1:9090/prometheus#' /opt/monitoring/provisioning/datasources/prometheus.yml \
 && sed -i 's#/var/lib/grafana/dashboards#/opt/monitoring-src/grafana/dashboards#' /opt/monitoring/provisioning/dashboards/dashboards.yml \
 && sed -i -e 's#http://localhost:8080#__API_URL__/ui/#' -e 's#http://localhost:8000/docs#__API_URL__/docs#' \
           -e 's#http://localhost:9090/alerts#/prometheus/alerts#' /opt/monitoring-src/grafana/dashboards/prediction_dashboard.json \
 && sed 's#__API_HOST__#example.onrender.com#' deploy/render/prometheus.render.yml > /tmp/check.yml \
 && /opt/prometheus/promtool check config /tmp/check.yml
ENV GF_PATHS_PROVISIONING=/opt/monitoring/provisioning \
    GF_SERVER_HTTP_ADDR=127.0.0.1 GF_SERVER_HTTP_PORT=3300 \
    GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s/grafana/ GF_SERVER_SERVE_FROM_SUB_PATH=true \
    GF_AUTH_ANONYMOUS_ENABLED=true GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer GF_AUTH_DISABLE_LOGIN_FORM=true \
    GF_USERS_DEFAULT_THEME=dark GF_USERS_ALLOW_SIGN_UP=false \
    GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/opt/monitoring-src/grafana/dashboards/prediction_dashboard.json \
    GF_ANALYTICS_REPORTING_ENABLED=false GF_ANALYTICS_CHECK_FOR_UPDATES=false \
    GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES=false GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED=true \
    GF_NEWS_NEWS_FEED_ENABLED=false GF_LIVE_MAX_CONNECTIONS=0 GF_SECURITY_ALLOW_EMBEDDING=true \
    GF_DASHBOARDS_MIN_REFRESH_INTERVAL=10s PORT=10000
# Run Grafana's schema migrations and provisioning once at build time (copied to /tmp at boot).
RUN mkdir -p /opt/grafana-seed /tmp/gl /tmp/gp \
 && GF_PATHS_DATA=/opt/grafana-seed GF_PATHS_LOGS=/tmp/gl GF_PATHS_PLUGINS=/tmp/gp \
    /opt/grafana/bin/grafana server --homepath /opt/grafana > /tmp/grafana-build.log 2>&1 & GPID=$! \
 ; for i in $(seq 1 120); do curl -fs http://127.0.0.1:3300/grafana/api/health >/dev/null && break; sleep 1; done \
 ; curl -fs http://127.0.0.1:3300/grafana/api/search | grep -q mlops-monitoring || { tail -40 /tmp/grafana-build.log; exit 1; } \
 ; kill $GPID; sleep 2
RUN sed 's/__PORT__/10000/' deploy/render/monitoring-nginx.conf.template > /tmp/nginx-check.conf && nginx -t -c /tmp/nginx-check.conf
CMD ["sh", "deploy/render/monitoring-start.sh"]
