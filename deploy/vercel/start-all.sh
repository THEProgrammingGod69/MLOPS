#!/bin/sh
# All-in-one entrypoint: API (+ demo traffic), Prometheus, Grafana behind nginx on $PORT.
#
# Vercel destroys an instance after under a minute without requests and starts a new one on
# the next visit, and holds incoming requests until the container's port is open. So boot
# order is what visitors actually see:
#   1. Prometheus starts with no scrape targets and receives the recorded hour of history.
#   2. Only then, with the API already answering, the real config is loaded. So `up` never
#      records a false 0 (that race was the "DOWN" tile) and charts are full on first paint.
#   3. nginx opens the port last. An instance that is still booting must never take traffic:
#      answering "not ready" made Grafana lose JavaScript chunks and go blank.
# Static files are cached at the CDN (nginx.conf.template), so page shells never wait for this.
PORT="${PORT:-8080}"
GF_SECURITY_ADMIN_PASSWORD="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export GF_SECURITY_ADMIN_PASSWORD
mkdir -p /tmp/prometheus /tmp/grafana/data /tmp/grafana/logs /tmp/grafana/plugins
cp -a /opt/grafana-seed/. /tmp/grafana/data/ 2>/dev/null || true

wait_for() { # url, half-seconds
  i=0
  until python -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)" "$1" 2>/dev/null; do
    i=$((i+1)); [ "$i" -ge "$2" ] && return 1; sleep 0.5
  done
}

wait_for_series() { # PromQL, half-seconds
  python - "$1" "$2" <<'PY'
import json, sys, time, urllib.parse, urllib.request
url = "http://127.0.0.1:9090/prometheus/api/v1/query?query=" + urllib.parse.quote(sys.argv[1])
for _ in range(int(sys.argv[2])):
    try:
        if json.load(urllib.request.urlopen(url, timeout=2))["data"]["result"]:
            break
    except Exception:
        pass
    time.sleep(0.5)
PY
}

PORT=8000 sh scripts/start-api.sh &
GF_PATHS_DATA=/tmp/grafana/data GF_PATHS_LOGS=/tmp/grafana/logs GF_PATHS_PLUGINS=/tmp/grafana/plugins \
  /opt/grafana/bin/grafana server --homepath /opt/grafana > /tmp/grafana.log 2>&1 &

wait_for http://127.0.0.1:8000/health 120
python deploy/vercel/seed_traffic.py

printf 'global:\n  scrape_interval: 5s\n' > /tmp/prometheus-active.yml
/opt/prometheus/prometheus --config.file=/tmp/prometheus-active.yml \
  --storage.tsdb.path=/tmp/prometheus --storage.tsdb.retention.time=2d \
  --web.listen-address=127.0.0.1:9090 --web.enable-remote-write-receiver \
  --web.external-url=/prometheus/ --web.route-prefix=/prometheus --log.level=warn &
PROMETHEUS_PID=$!

wait_for http://127.0.0.1:9090/prometheus/-/ready 60
python deploy/vercel/replay_history.py
cp /opt/monitoring/prometheus.yml /tmp/prometheus-active.yml
kill -HUP "$PROMETHEUS_PID"

wait_for http://127.0.0.1:3300/grafana/api/health 60
wait_for_series 'ALERTS{alertname="StudentDropoutRiskAbove50"}' 30
sed "s/__PORT__/${PORT}/" deploy/vercel/nginx.conf.template > /tmp/nginx.conf
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
