#!/bin/sh
# API_TARGET  host[:port] of the API, e.g. mlops-ews-api.onrender.com   (required)
# API_SCHEME  https (default) or http
# PORT        listen port (default 9090)
set -e
: "${API_TARGET:?Set API_TARGET to the API host, e.g. mlops-ews-api.onrender.com}"
sed -e "s#__API_TARGET__#${API_TARGET}#" -e "s#__API_SCHEME__#${API_SCHEME:-https}#" \
  /etc/prometheus/prometheus.yml.template > /tmp/prometheus.yml
exec /bin/prometheus --config.file=/tmp/prometheus.yml --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time=7d --web.listen-address="0.0.0.0:${PORT:-9090}"
