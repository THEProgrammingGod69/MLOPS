"""Warm a freshly started demo instance so every dashboard has data within seconds.

Vercel scales container instances to zero and starts new ones on demand, and each
instance has its own in-memory monitor and Prometheus. Without seeding, a new instance
shows empty panels until the drift window (2000 predictions) fills at demo-traffic pace.
This sends one full-window batch plus a burst of single predictions, then exits; the
regular simulator (scripts/start-api.sh) keeps traffic flowing afterwards.
"""
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "scripts")
import simulate_traffic as sim  # noqa: E402

BASE = os.environ.get("SEED_URL", "http://127.0.0.1:8000")
BATCH_SIZE = int(os.environ.get("SEED_BATCH", "2000"))
SINGLES = int(os.environ.get("SEED_SINGLES", "240"))


def main():
    rng = random.Random()
    marginals, categories = sim.load_marginals("configs/drift_reference_profile.json",
                                               "reports/eda/numeric_summary.csv")

    def student(scenario="normal"):
        s = sim.make_student(rng, marginals, categories, scenario)
        if rng.random() < 0.6:
            s["gender"] = "M" if rng.random() < 0.55 else "F"
        return s

    batch_status = sim.post(f"{BASE}/api/v1/predict/batch",
                            {"students": [student() for _ in range(BATCH_SIZE)]}, timeout=120)

    def single(i):
        explain = "true" if i % 3 == 0 else "false"
        return sim.post(f"{BASE}/api/v1/predict?include_explanation={explain}", student(), timeout=30)

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(single, range(SINGLES)))
    print(f"seed: batch={batch_status} singles_ok={sum(s == 200 for s in statuses)}/{SINGLES}", flush=True)


if __name__ == "__main__":
    main()
