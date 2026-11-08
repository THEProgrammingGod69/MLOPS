#!/bin/sh
# All-in-one entrypoint: API (+ demo traffic), Prometheus, Grafana behind nginx on $PORT.
#
# Vercel destroys an instance after under a minute without requests and starts a new one on
# the next visit, so boot order is what visitors actually see:
#   1. nginx opens immediately: the web UI is static and renders at once; /grafana and
#      /prometheus answer with a self-refreshing page until /tmp/stack-ready exists.
#   2. Prometheus is held back until the API answers, so `up` never records a false 0
#      (that race was the "DOWN" tile) and its TSDB already holds the replayed hour.
PORT="${PORT:-8080}"
GF_SECURITY_ADMIN_PASSWORD="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export GF_SECURITY_ADMIN_PASSWORD
mkdir -p /tmp/prometheus /tmp/grafana/data /tmp/grafana/logs /tmp/grafana/plugins
rm -f /tmp/stack-ready
cp -a /opt/grafana-seed/. /tmp/grafana/data/ 2>/dev/null || true

sed "s/__PORT__/${PORT}/" deploy/vercel/nginx.conf.template > /tmp/nginx.conf
nginx -c /tmp/nginx.conf -g 'daemon off;' &
NGINX_PID=$!

wait_for() { # url, half-seconds
  i=0
  until python -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)" "$1" 2>/dev/null; do
    i=$((i+1)); [ "$i" -ge "$2" ] && return 1; sleep 0.5
  done
}

PORT=8000 sh scripts/start-api.sh &
GF_PATHS_DATA=/tmp/grafana/data GF_PATHS_LOGS=/tmp/grafana/logs GF_PATHS_PLUGINS=/tmp/grafana/plugins \
  /opt/grafana/bin/grafana server --homepath /opt/grafana > /tmp/grafana.log 2>&1 &
python deploy/vercel/replay_history.py &
REPLAY_PID=$!

wait_for http://127.0.0.1:8000/health 120
python deploy/vercel/seed_traffic.py
wait "$REPLAY_PID"

/opt/prometheus/prometheus --config.file=/opt/monitoring/prometheus.yml \
  --storage.tsdb.path=/tmp/prometheus --storage.tsdb.retention.time=2d \
  --web.listen-address=127.0.0.1:9090 \
  --web.external-url=/prometheus/ --web.route-prefix=/prometheus --log.level=warn &

wait_for http://127.0.0.1:9090/prometheus/-/ready 60
wait_for http://127.0.0.1:3300/grafana/api/health 60
sleep 6  # one scrape and one rule evaluation, so the first dashboard paint is complete
touch /tmp/stack-ready
wait "$NGINX_PID"
