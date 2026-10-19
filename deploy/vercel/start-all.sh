#!/bin/sh
# All-in-one entrypoint: API (+ demo traffic), Prometheus, Grafana behind nginx on $PORT.
set -e
PORT="${PORT:-8080}"
# Login form is disabled (anonymous viewers); a random admin password also closes basic auth.
GF_SECURITY_ADMIN_PASSWORD="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
export GF_SECURITY_ADMIN_PASSWORD
mkdir -p /tmp/prometheus /tmp/grafana/data /tmp/grafana/logs /tmp/grafana/plugins

PORT=8000 sh scripts/start-api.sh &

/opt/prometheus/prometheus --config.file=/opt/monitoring/prometheus.yml \
  --storage.tsdb.path=/tmp/prometheus --storage.tsdb.retention.time=2d \
  --web.listen-address=127.0.0.1:9090 \
  --web.external-url=/prometheus/ --web.route-prefix=/prometheus &

GF_PATHS_DATA=/tmp/grafana/data GF_PATHS_LOGS=/tmp/grafana/logs GF_PATHS_PLUGINS=/tmp/grafana/plugins \
  /opt/grafana/bin/grafana server --homepath /opt/grafana &

sed "s/__PORT__/${PORT}/" deploy/vercel/nginx.conf.template > /tmp/nginx.conf
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
