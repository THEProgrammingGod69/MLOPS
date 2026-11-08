"""Record an hour of monitoring history at image build time (deploy/vercel only).

Vercel destroys idle containers within a minute, and every new one starts with an empty
Prometheus. So the image carries a recording: the real API and model score simulated
students while /metrics is captured once per simulated 15 s step. ``replay_history.py``
writes it into Prometheus at boot, ending at the current time, so a new instance opens
with a full hour of charts. The dashboard says plainly that this history is a replay.
"""
import gzip
import json
import os
import random
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "scripts")
import simulate_traffic as sim  # noqa: E402

PORT = 8000
BASE = f"http://127.0.0.1:{PORT}"
STEPS = int(os.environ.get("RECORD_STEPS", "240"))
OUTPUT = os.environ.get("RECORD_OUTPUT", "/opt/replay/metrics.json.gz")
# Excluded: per-student alert rows (only meaningful live), process internals, and series that
# would claim a process start time from build day.
SKIP_PREFIXES = ("student_dropout_alert_open", "python_", "process_", "student_dropout_app_start_time_seconds", "student_dropout_model_info",
                 "student_dropout_offline")


def phase(step):
    position = step / STEPS
    return "engagement-drop" if 0.55 <= position < 0.8 else "normal"


def scrape():
    with urllib.request.urlopen(f"{BASE}/metrics", timeout=30) as response:
        text = response.read().decode()
    return [line for line in text.splitlines() if line and not line.startswith("#") and not line.startswith(SKIP_PREFIXES)]


def wait_for_api():
    for _ in range(240):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=2)
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit("API did not start during recording")


def main():
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
                              env={**os.environ, "DEMO_TRAFFIC_RPS": "0"})
    try:
        wait_for_api()
        rng = random.Random(2026)
        marginals, categories = sim.load_marginals("configs/drift_reference_profile.json", "reports/eda/numeric_summary.csv")
        snapshots = []
        for step in range(STEPS):
            scenario = phase(step)
            batch = [sim.make_student(rng, marginals, categories, scenario) for _ in range(rng.randint(10, 26))]
            sim.post(f"{BASE}/api/v1/predict/batch", {"students": batch}, timeout=60)
            for i in range(3):
                student = sim.make_student(rng, marginals, categories, scenario)
                if rng.random() < 0.6:
                    student["gender"] = "M" if rng.random() < 0.55 else "F"
                sim.post(f"{BASE}/api/v1/predict?include_explanation={'true' if i == 0 else 'false'}", student, timeout=30)
            snapshots.append(scrape())
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        with gzip.open(OUTPUT, "wt", encoding="utf-8") as f:
            json.dump(snapshots, f)
        print(f"recorded {len(snapshots)} snapshots, {len(snapshots[-1])} series", flush=True)
    finally:
        server.terminate()
        server.wait(timeout=20)


if __name__ == "__main__":
    main()
