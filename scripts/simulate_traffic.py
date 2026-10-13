"""Synthetic traffic generator for demos of the monitoring stack.

Sends realistic prediction traffic to the API so the Grafana dashboard and the
web UI have something to show. Standard library only, so it runs anywhere
Python 3.8+ runs (including the plain ``python:3.10-slim`` container).

Students are sampled with a Gaussian copula: one latent "engagement" factor per
student, and each numeric feature drawn from its reference marginal (the drift
reference profile where available, otherwise the EDA quantiles). In the
``normal`` scenario the live drift monitor should therefore stay quiet, and the
other scenarios shift the latent factor to produce drift on purpose:

    normal            reference-like population
    engagement-drop   VLE activity collapses (drift on click/activity features, risk rises)
    assessment-shock  scores fall and failures rise (drift on assessment features)

Examples::

    python scripts/simulate_traffic.py                                    # 5 req/s, normal, forever
    python scripts/simulate_traffic.py --schedule normal:300,engagement-drop:300 --rps 8
    python scripts/simulate_traffic.py --url http://api:8000 --duration 120
"""
import argparse
import csv
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from statistics import NormalDist

PHI = NormalDist().cdf
SCENARIOS = ("normal", "engagement-drop", "assessment-shock")
FLOAT_FEATURES = {"asm_mean_score", "asm_score_std", "asm_average_delay"}

# Quantile points (min, 25%, 50%, 75%, 95%, max) for features absent from both sources.
FALLBACK_QUANTILES = {
    "registration_day": (-300.0, -100.0, -57.0, -29.0, -10.0, 20.0),
}
# Discrete features whose EDA quartiles are too coarse to interpolate. Chosen to match
# numeric_summary.csv: mean 0.91 submissions, 25.7 % with none (no score -> missing mean
# score) and 11.8 % with two or more (the only students with a score standard deviation).
DISCRETE_FALLBACKS = {
    "asm_submission_count": {0: 0.26, 1: 0.62, 2: 0.10, 3: 0.02},
}
CATEGORY_FREQUENCIES = {
    "highest_education": {"A Level or Equivalent": 0.44, "Lower Than A Level": 0.39, "HE Qualification": 0.15,
                          "Post Graduate Qualification": 0.01, "No Formal quals": 0.01},
    "code_module": {"AAA": 0.03, "BBB": 0.2, "CCC": 0.12, "DDD": 0.18, "EEE": 0.08, "FFF": 0.24, "GGG": 0.15},
    "code_presentation": {"2013B": 0.15, "2013J": 0.25, "2014B": 0.23, "2014J": 0.37},
}
COURSES = {
    "AAA": {"2013J": 268, "2014J": 269},
    "BBB": {"2013B": 240, "2013J": 268, "2014B": 234, "2014J": 262},
    "CCC": {"2014B": 241, "2014J": 269},
    "DDD": {"2013B": 240, "2013J": 261, "2014B": 241, "2014J": 262},
    "EEE": {"2013J": 268, "2014B": 241, "2014J": 269},
    "FFF": {"2013B": 240, "2013J": 268, "2014B": 241, "2014J": 269},
    "GGG": {"2013J": 261, "2014B": 241, "2014J": 269},
}
# Loading of each feature on the latent engagement factor (sign = direction of the relationship).
LOADINGS = {
    "vle_total_clicks": 0.85, "vle_active_days": 0.8, "vle_clicks_last_7_days": 0.75,
    "vle_clicks_last_14_days": 0.8, "vle_forum_clicks": 0.6, "vle_resource_clicks": 0.6,
    "vle_quiz_clicks": 0.55, "vle_activity_type_diversity": 0.7, "vle_days_since_last_activity": -0.6,
    "asm_submission_count": 0.5, "asm_mean_score": 0.45, "asm_average_delay": -0.3,
    "asm_failed_count": -0.35, "registration_day": -0.2, "studied_credits": 0.0,
    "num_of_prev_attempts": -0.15, "asm_score_std": 0.0,
}
# scenario -> {feature name prefix: shift of the latent factor, in standard deviations;
# negative = towards disengagement, applied along each feature's loading sign}
CLICK_COUNTERS = {"vle_total_clicks", "vle_clicks_last_14_days", "vle_clicks_last_7_days"}
SHIFTS = {
    "normal": {},
    "engagement-drop": {"vle_": -1.4},
    "assessment-shock": {"asm_mean_score": -1.2, "asm_failed_count": -1.5, "asm_average_delay": -1.0},
}


class Marginal:
    """Inverse CDF over segments [(cum_prob_start, cum_prob_end, lo, hi), ...].

    Bin shares are exact (that is what PSI measures). Inside a bin, values are spread
    to mimic right-skewed count data: geometric interpolation for interior bins and a
    truncated exponential for the open-ended top bin, so window means stay close to
    the reference means instead of being dragged up by a uniform draw towards the max.
    """

    def __init__(self, segments, integer):
        self.segments = [s for s in segments if s[1] > s[0]]
        self.integer = integer

    def _within(self, frac, lo, hi, last):
        if hi <= lo:
            return lo
        if last and lo > 0 and hi > 2 * lo:
            scale = 0.35 * lo
            return lo - scale * math.log(1.0 - frac * (1.0 - math.exp(-(hi - lo) / scale)))
        if lo > 0 and hi > 1.5 * lo:
            return lo * (hi / lo) ** frac
        return lo + frac * (hi - lo)

    def ppf(self, u):
        for i, (start, end, lo, hi) in enumerate(self.segments):
            if u < end:
                value = self._within((u - start) / (end - start), lo, hi, i == len(self.segments) - 1)
                return int(math.floor(value)) if self.integer else value
        hi = self.segments[-1][3]
        return int(math.floor(hi)) if self.integer else hi


def marginal_from_profile(spec, integer):
    bounds = [spec["min"]] + list(spec["edges"]) + [spec["max"]]
    present = 1.0 - spec.get("missing_rate", 0.0)
    segments, cumulative = [], 0.0
    for i, share in enumerate(spec["proportions"]):
        segments.append((cumulative, cumulative + share, bounds[i], bounds[i + 1]))
        cumulative += share
    return Marginal(segments, integer), present


def marginal_from_quantiles(points, integer):
    probabilities = (0.0, 0.25, 0.5, 0.75, 0.95, 1.0)
    segments = [(probabilities[i], probabilities[i + 1], points[i], points[i + 1]) for i in range(5)]
    return Marginal(segments, integer), 1.0


def load_marginals(profile_path, summary_path):
    marginals = {}
    try:
        with open(summary_path, newline="") as f:
            for row in csv.DictReader(f):
                name = row[""]
                points = tuple(float(row[k]) for k in ("min", "25%", "50%", "75%", "95%", "max"))
                total = float(row["count"]) + float(row["missing"])
                marginal, _ = marginal_from_quantiles(points, name not in FLOAT_FEATURES)
                marginals[name] = (marginal, float(row["count"]) / total if total else 1.0)
    except OSError:
        print(f"warning: {summary_path} not found, using built-in quantiles only", file=sys.stderr)
    for name, points in FALLBACK_QUANTILES.items():
        marginals.setdefault(name, marginal_from_quantiles(points, True))
    for name, distribution in DISCRETE_FALLBACKS.items():
        segments, cumulative = [], 0.0
        for value, share in distribution.items():
            segments.append((cumulative, cumulative + share, value, value))
            cumulative += share
        marginals[name] = (Marginal(segments, True), 1.0)
    categories = dict(CATEGORY_FREQUENCIES)
    try:
        with open(profile_path) as f:
            profile = json.load(f)
        for name, spec in profile.get("numeric", {}).items():
            if "min" in spec and "max" in spec:
                marginals[name] = marginal_from_profile(spec, name not in FLOAT_FEATURES)
        for name, spec in profile.get("categorical", {}).items():
            categories[name] = spec["frequencies"]
    except (OSError, ValueError):
        print(f"warning: reference profile {profile_path} not readable, using EDA quantiles", file=sys.stderr)
    categories["course_joint"] = course_joint(categories["code_module"], categories["code_presentation"])
    return marginals, categories


def course_joint(module_freq, presentation_freq, iterations=200):
    """Joint (module, presentation) distribution over the 22 real courses matching both
    marginals, by iterative proportional fitting (max-entropy solution)."""
    cells = {(m, p): 1.0 for m, presentations in COURSES.items() for p in presentations}
    for _ in range(iterations):
        for target, axis in ((module_freq, 0), (presentation_freq, 1)):
            totals = {}
            for cell, weight in cells.items():
                totals[cell[axis]] = totals.get(cell[axis], 0.0) + weight
            for cell in cells:
                if totals[cell[axis]] > 0:
                    cells[cell] *= target.get(cell[axis], 0.0) / totals[cell[axis]]
    total = sum(cells.values())
    return {cell: weight / total for cell, weight in cells.items()}


def pick(rng, frequencies):
    r, cumulative = rng.random() * sum(frequencies.values()), 0.0
    for key, weight in frequencies.items():
        cumulative += weight
        if r < cumulative:
            return key
    return key


def shift_for(scenario, feature):
    for prefix, shift in SHIFTS[scenario].items():
        if feature.startswith(prefix):
            return shift
    return 0.0


def make_student(rng, marginals, categories, scenario):
    z = rng.gauss(0.0, 1.0)
    clicks = rng.gauss(0.0, 1.0)  # shared by the nested click counters so 7d <= 14d <= total holds naturally
    student = {}
    for feature, loading in LOADINGS.items():
        marginal, _ = marginals[feature]
        noise = rng.gauss(0.0, 1.0)
        if feature in CLICK_COUNTERS:
            noise = 0.95 * clicks + math.sqrt(1.0 - 0.95 ** 2) * noise
        latent = loading * z + math.sqrt(1.0 - loading ** 2) * noise
        if loading:
            latent += shift_for(scenario, feature) * math.copysign(1.0, loading)
        u = min(max(PHI(latent), 1e-6), 1 - 1e-6)
        student[feature] = marginal.ppf(u)

    module, presentation = pick(rng, categories["course_joint"])
    student.update(
        highest_education=pick(rng, categories["highest_education"]),
        code_module=module,
        code_presentation=presentation,
        module_presentation_length=COURSES[module][presentation],
    )
    # Keep the engagement counters internally consistent.
    student["vle_clicks_last_14_days"] = max(student["vle_clicks_last_14_days"], student["vle_clicks_last_7_days"])
    student["vle_total_clicks"] = max(student["vle_total_clicks"], student["vle_clicks_last_14_days"])
    if student["vle_total_clicks"] == 0:
        student["vle_days_since_last_activity"] = None
    if student["asm_submission_count"] == 0:
        student.update(asm_mean_score=None, asm_score_std=None, asm_average_delay=None, asm_failed_count=0)
    elif student["asm_submission_count"] < 2:
        student["asm_score_std"] = None
    if student["asm_mean_score"] is not None:
        student["asm_mean_score"] = round(min(max(student["asm_mean_score"], 0.0), 100.0), 1)
    for key in ("asm_score_std", "asm_average_delay"):
        if student[key] is not None:
            student[key] = round(student[key], 2)
    return student


def post(url, payload, timeout=10):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, OSError):
        return None


def parse_schedule(value, duration):
    phases = []
    for part in value.split(","):
        name, _, seconds = part.partition(":")
        if name not in SCENARIOS:
            raise SystemExit(f"Unknown scenario '{name}'. Choose from: {', '.join(SCENARIOS)}")
        phases.append((name, float(seconds) if seconds else None))
    if duration and phases[-1][1] is None:
        phases[-1] = (phases[-1][0], duration)
    return phases


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send synthetic prediction traffic to the API.")
    parser.add_argument("--url", default=os.environ.get("API_URL", "http://localhost:8000"))
    parser.add_argument("--rps", type=float, default=float(os.environ.get("SIM_RPS", 5)))
    parser.add_argument("--schedule", default=os.environ.get("SIM_SCHEDULE", "normal"),
                        help="Comma list of scenario[:seconds]; the last phase without seconds runs forever")
    parser.add_argument("--duration", type=float, default=None, help="Seconds for the final phase")
    parser.add_argument("--explain-ratio", type=float, default=0.3, help="Share of requests asking for SHAP")
    parser.add_argument("--gender-ratio", type=float, default=0.6, help="Share of requests carrying gender")
    parser.add_argument("--batch-every", type=float, default=30.0, help="Seconds between batch requests (0 = off)")
    parser.add_argument("--invalid-ratio", type=float, default=0.01, help="Share of deliberately invalid payloads")
    parser.add_argument("--profile", default="configs/drift_reference_profile.json")
    parser.add_argument("--summary", default="reports/eda/numeric_summary.csv")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    marginals, categories = load_marginals(args.profile, args.summary)
    base = args.url.rstrip("/")
    interval = 1.0 / args.rps if args.rps > 0 else 1.0
    phases = parse_schedule(args.schedule, args.duration)
    stats = {"sent": 0, "ok": 0, "failed": 0}
    last_batch = time.monotonic()
    print(f"Sending traffic to {base} at {args.rps:g} req/s, schedule: "
          + ", ".join(f"{n}{'' if s is None else f' ({s:g}s)'}" for n, s in phases), flush=True)

    try:
        for scenario, seconds in phases:
            phase_end = None if seconds is None else time.monotonic() + seconds
            print(f"-> phase '{scenario}'", flush=True)
            while phase_end is None or time.monotonic() < phase_end:
                tick = time.monotonic()
                student = make_student(rng, marginals, categories, scenario)
                if rng.random() < args.gender_ratio:
                    student["gender"] = "M" if rng.random() < 0.55 else "F"
                if rng.random() < args.invalid_ratio:
                    student["vle_total_clicks"] = -1  # rejected with HTTP 422
                explain = "true" if rng.random() < args.explain_ratio else "false"
                status = post(f"{base}/api/v1/predict?include_explanation={explain}", student)
                stats["sent"] += 1
                stats["ok" if status == 200 else "failed"] += 1

                if args.batch_every and time.monotonic() - last_batch >= args.batch_every:
                    batch = [make_student(rng, marginals, categories, scenario) for _ in range(rng.randint(20, 120))]
                    post(f"{base}/api/v1/predict/batch", {"students": batch}, timeout=60)
                    last_batch = time.monotonic()
                if stats["sent"] % 100 == 0:
                    print(f"   sent={stats['sent']} ok={stats['ok']} non-200={stats['failed']}", flush=True)
                time.sleep(max(0.0, interval - (time.monotonic() - tick)))
    except KeyboardInterrupt:
        pass
    print(f"Done: {stats}", flush=True)
    return stats


if __name__ == "__main__":
    main()
