"""Send the build-time recording into a freshly started Prometheus.

promtool cannot be used here: its block writer preallocates a 512 MiB chunk file, more than
the serverless /tmp offers. Prometheus's remote-write receiver appends to the head block
instead. start-all.sh runs this before any scrape target exists, because the head rejects
samples far older than its newest one, and the recording ends just before now.

Remote write is protobuf over snappy. The messages are three small fields, so both are
encoded by hand (snappy as one uncompressed literal, which is valid over loopback) to keep
the image free of extra dependencies. Any failure is non-fatal: the instance then simply
starts without history.
"""
import gzip
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request

SOURCE = os.environ.get("RECORD_OUTPUT", "/opt/replay/metrics.json.gz")
WRITE_URL = os.environ.get("PROMETHEUS_WRITE_URL", "http://127.0.0.1:9090/prometheus/api/v1/write")
STEP_SECONDS = 15
GAP_SECONDS = 10  # the first live scrape follows shortly, so history and live samples meet without overlapping
MAX_AGE_SECONDS = 3450  # the head accepts samples up to one hour behind its newest sample
BATCH_SERIES = 150
BASE_LABELS = {"environment": "vercel", "instance": "127.0.0.1:8000", "job": "mlops-api"}
SAMPLE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})? (\S+)$")
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')
UNESCAPE = re.compile(r"\\(.)")


def varint(value):
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(number, payload):
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def encode_series(labels, samples):
    body = b"".join(field(1, field(1, k.encode()) + field(2, v.encode())) for k, v in sorted(labels.items()))
    for timestamp_ms, value in samples:
        body += field(2, b"\x09" + struct.pack("<d", value) + b"\x10" + varint(timestamp_ms))
    return field(1, body)


def snappy_literal(data):
    return varint(len(data)) + b"\xfc" + struct.pack("<I", len(data) - 1) + data


def parse_labels(text):
    if not text:
        return {}
    return {k: UNESCAPE.sub(lambda m: {"n": "\n"}.get(m.group(1), m.group(1)), v) for k, v in LABEL.findall(text)}


def collect(snapshots, end_time):
    """Group the snapshots by series, keeping only samples the head will accept."""
    series = {}
    count = len(snapshots)
    oldest = end_time - MAX_AGE_SECONDS
    for index, lines in enumerate(snapshots):
        timestamp = end_time - (count - 1 - index) * STEP_SECONDS
        if timestamp < oldest:
            continue
        series.setdefault("up", ({"__name__": "up", **BASE_LABELS}, []))[1].append((timestamp * 1000, 1.0))
        for line in lines:
            match = SAMPLE.match(line)
            if match is None:
                continue
            name, raw_labels, value = match.groups()
            entry = series.get(f"{name}{{{raw_labels}}}")
            if entry is None:
                entry = ({"__name__": name, **parse_labels(raw_labels), **BASE_LABELS}, [])
                series[f"{name}{{{raw_labels}}}"] = entry
            entry[1].append((timestamp * 1000, float(value)))
    return list(series.values())


def send(batch):
    body = snappy_literal(b"".join(encode_series(labels, samples) for labels, samples in batch))
    request = urllib.request.Request(WRITE_URL, data=body, method="POST", headers={
        "Content-Encoding": "snappy", "Content-Type": "application/x-protobuf", "X-Prometheus-Remote-Write-Version": "0.1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status


def main():
    started = time.time()
    if not os.path.exists(SOURCE):
        print("replay: no recording in this image", flush=True)
        return
    with gzip.open(SOURCE, "rt", encoding="utf-8") as f:
        snapshots = json.load(f)
    series = collect(snapshots, int(time.time()) - GAP_SECONDS)
    samples = sum(len(s[1]) for s in series)
    for start in range(0, len(series), BATCH_SERIES):
        send(series[start:start + BATCH_SERIES])
    print(f"replay: {samples} samples across {len(series)} series in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(f"replay: Prometheus refused the history ({exc.code}): {exc.read()[:400]!r}", flush=True)
    except Exception as exc:  # a missing history must never stop the instance from booting
        print(f"replay: skipped ({type(exc).__name__}: {exc})", flush=True)
    sys.exit(0)
