#!/bin/sh
# Monitoring service entrypoint on Render. Render holds incoming requests until the port opens,
# so nothing below is visible to a visitor until it is complete:
#   1. Wake the API service (free services sleep after 15 idle minutes) and wait until it answers.
#   2. Load the API's recorded hour of history into a Prometheus that has no scrape targets yet.
#   3. Only then point Prometheus at the API: `up` never records a false 0 for a sleeping API.
#   4. Open the port.
PORT="${PORT:-10000}"
API_URL="${API_URL%/}"
API_HOST="${API_URL#https://}"
GF_SECURITY_ADMIN_PASSWORD="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export GF_SECURITY_ADMIN_PASSWORD
mkdir -p /tmp/prometheus /tmp/grafana/data /tmp/grafana/logs /tmp/grafana/plugins
cp -a /opt/grafana-seed/. /tmp/grafana/data/ 2>/dev/null || true
sed -i "s#__API_URL__#${API_URL}#g" /opt/monitoring-src/grafana/dashboards/prediction_dashboard.json

GF_PATHS_DATA=/tmp/grafana/data GF_PATHS_LOGS=/tmp/grafana/logs GF_PATHS_PLUGINS=/tmp/grafana/plugins \
  /opt/grafana/bin/grafana server --homepath /opt/grafana > /tmp/grafana.log 2>&1 &

wait_for() { # url, attempts, per-attempt timeout in seconds
  i=0
  until python -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=float(sys.argv[2]))" "$1" "$3" 2>/dev/null; do
    i=$((i+1)); [ "$i" -ge "$2" ] && return 1; sleep 1
  done
}

echo "monitoring: waking ${API_URL}"
wait_for "${API_URL}/health" 60 30 || echo "monitoring: API did not answer, starting anyway"
curl -fsS --max-time 120 "${API_URL}/api/v1/replay" -o /tmp/replay.json.gz || echo "monitoring: no replay available"

printf 'global:\n  scrape_interval: 15s\n' > /tmp/prometheus-active.yml
/opt/prometheus/prometheus --config.file=/tmp/prometheus-active.yml \
  --storage.tsdb.path=/tmp/prometheus --storage.tsdb.retention.time=2d \
  --web.listen-address=127.0.0.1:9090 --web.enable-remote-write-receiver \
  --web.external-url=/prometheus/ --web.route-prefix=/prometheus --log.level=warn &
PROMETHEUS_PID=$!
wait_for http://127.0.0.1:9090/prometheus/-/ready 60 2

RECORD_OUTPUT=/tmp/replay.json.gz REPLAY_LABELS="environment=render,instance=api,job=mlops-api" \
  python deploy/render/replay_history.py
sed "s#__API_HOST__#${API_HOST}#" deploy/render/prometheus.render.yml > /tmp/prometheus-active.yml
kill -HUP "$PROMETHEUS_PID"

wait_for http://127.0.0.1:3300/grafana/api/health 90 2
python - <<'PY'
import json, time, urllib.parse, urllib.request
url = "http://127.0.0.1:9090/prometheus/api/v1/query?query=" + urllib.parse.quote('ALERTS{alertname="StudentDropoutRiskAbove50"}')
for _ in range(40):
    try:
        if json.load(urllib.request.urlopen(url, timeout=2))["data"]["result"]:
            break
    except Exception:
        pass
    time.sleep(1)
PY
sed "s/__PORT__/${PORT}/" deploy/render/monitoring-nginx.conf.template > /tmp/nginx.conf
echo "monitoring: ready"
exec nginx -e stderr -c /tmp/nginx.conf -g 'daemon off;'
