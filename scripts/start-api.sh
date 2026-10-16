#!/bin/sh
# Container entrypoint for the inference API.
#   PORT               listen port (default 8000)
#   DEMO_TRAFFIC_RPS   if > 0, run scripts/simulate_traffic.py against this API in the background
#   SIM_SCHEDULE       simulator schedule, repeated forever (default: normal 20 min, engagement drop 10 min)
set -e
PORT="${PORT:-8000}"

if [ -n "$DEMO_TRAFFIC_RPS" ] && [ "$DEMO_TRAFFIC_RPS" != "0" ]; then
  (
    until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=2)" 2>/dev/null; do
      sleep 2
    done
    while true; do
      python scripts/simulate_traffic.py --url "http://127.0.0.1:${PORT}" --rps "$DEMO_TRAFFIC_RPS" \
        --batch-every 60 --schedule "${SIM_SCHEDULE:-normal:1200,engagement-drop:600}" || sleep 5
    done
  ) &
fi

exec uvicorn src.api.main:app --host 0.0.0.0 --port "$PORT"
