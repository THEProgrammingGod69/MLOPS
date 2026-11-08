"""Write the build-time recording into Prometheus's data directory at boot.

Rebases the snapshots so the last one lands just before now, adds the labels Prometheus
would have attached, and lets promtool build TSDB blocks. Any failure is non-fatal: the
instance then simply starts without history.
"""
import gzip
import json
import os
import re
import subprocess
import sys
import time

SOURCE = os.environ.get("RECORD_OUTPUT", "/opt/replay/metrics.json.gz")
TSDB = os.environ.get("TSDB_PATH", "/tmp/prometheus")
PROMTOOL = os.environ.get("PROMTOOL", "/opt/prometheus/promtool")
STEP_SECONDS = 15
GAP_SECONDS = 20  # leaves room for the first live scrape, so history and live samples never overlap
LABELS = 'environment="vercel",instance="127.0.0.1:8000",job="mlops-api"'
SAMPLE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})? (\S+)$")


def to_openmetrics(snapshots, end_time):
    count = len(snapshots)
    for index, lines in enumerate(snapshots):
        timestamp = end_time - (count - 1 - index) * STEP_SECONDS
        yield f"up{{{LABELS}}} 1 {timestamp}\n"
        for line in lines:
            match = SAMPLE.match(line)
            if match is None:
                continue
            name, labels, value = match.groups()
            merged = f"{labels},{LABELS}" if labels else LABELS
            yield f"{name}{{{merged}}} {value} {timestamp}\n"
    yield "# EOF\n"


def main():
    started = time.time()
    if not os.path.exists(SOURCE):
        print("replay: no recording in this image", flush=True)
        return 0
    with gzip.open(SOURCE, "rt", encoding="utf-8") as f:
        snapshots = json.load(f)
    os.makedirs(TSDB, exist_ok=True)
    path = "/tmp/replay.om"
    with open(path, "w", encoding="utf-8") as out:
        out.writelines(to_openmetrics(snapshots, int(time.time()) - GAP_SECONDS))
    result = subprocess.run([PROMTOOL, "tsdb", "create-blocks-from", "openmetrics", path, TSDB], capture_output=True, text=True, timeout=120)
    os.remove(path)
    if result.returncode != 0:
        print(f"replay: promtool failed: {result.stderr[-800:]}", flush=True)
        return 0
    print(f"replay: {len(snapshots)} snapshots written in {time.time() - started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a missing history must never stop the instance from booting
        print(f"replay: skipped ({type(exc).__name__}: {exc})", flush=True)
        sys.exit(0)
