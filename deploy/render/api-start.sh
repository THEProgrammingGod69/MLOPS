#!/bin/sh
# API service entrypoint on Render: start the API, then fill the drift window and open the
# deterministic demo alert cases once it answers (the same seed on every boot).
PORT="${PORT:-10000}"
export PORT
(
  until python -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)" "http://127.0.0.1:${PORT}/health" 2>/dev/null; do
    sleep 1
  done
  SEED_URL="http://127.0.0.1:${PORT}" python deploy/vercel/seed_traffic.py
) &
exec sh scripts/start-api.sh
