"""Keeps real users' alert cases in step across serverless instances.

Vercel spreads concurrent requests over several containers and offers no way to cap them or
pin a client to one, while each container holds its own alert desk and its own Prometheus.
Left alone, an alert raised on one container flickers in Grafana as panel queries land on others.

Instances cannot address each other, so each one calls the public URL and the platform's
router delivers it to some peer: both sides then merge, and repeated calls reach the pool.

Calls go one at a time, because bursts are what make the platform start more containers.
They run only for a short while after a real visitor was seen, so a quiet instance makes no
calls of its own and can still scale to zero. Disabled unless ``ALERT_SYNC_URL`` is set.
"""
import json
import logging
import os
import threading
import time
import urllib.request

from src.api.alert_desk import alert_desk

logger = logging.getLogger(__name__)

SYNC_URL = os.environ.get("ALERT_SYNC_URL", "").rstrip("/")
INTERVAL_SECONDS = 3.0
ACTIVE_WINDOW_SECONDS = 40.0
TIMEOUT_SECONDS = 5.0

_last_visitor = [0.0]


def touch() -> None:
    _last_visitor[0] = time.time()


def is_active() -> bool:
    return time.time() - _last_visitor[0] < ACTIVE_WINDOW_SECONDS


def sync_once() -> None:
    request = urllib.request.Request(f"{SYNC_URL}/api/v1/alerts/sync", data=json.dumps(alert_desk.sync_state()).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Alert-Sync": "1", "User-Agent": "early-warning-sync"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        alert_desk.merge(json.load(response))


def _run() -> None:
    while True:
        time.sleep(INTERVAL_SECONDS)
        if not is_active():
            continue
        try:
            sync_once()
        except Exception as exc:  # a missed round is repaired by the next one
            logger.debug("alert sync skipped: %s", exc)


def start() -> None:
    if SYNC_URL:
        threading.Thread(target=_run, name="alert-sync", daemon=True).start()
