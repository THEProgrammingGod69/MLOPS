"""Decision lab: what the model suggests doing, not just what it predicts.

* ``rescue_plans``   smallest set of concrete student actions that brings the predicted
  risk under the target. Greedy by risk reduction per unit of effort, then pruned.
* ``plan_triage``    spends a limited number of advisor hours where the model says
  outreach can move a student furthest, and compares it with highest-risk-first.
* ``stress_test``    shocks a whole cohort (LMS outage, exam slump) and counts who crosses
  the alert threshold.

Every number is the model's response to changed inputs. It indicates where help is likely
to matter; it is not a causal estimate of what an intervention will achieve.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

import numpy as np
import pandas as pd

from src.api.alert_desk import ALERT_THRESHOLD
from src.api.inference import inference_service
from src.api.feature_catalog import feature_label
from src.models.train_baselines import PREDICTIVE_FEATURES

MAX_STEPS = 6
TRIAGE_STEPS = 3
TIER_MINUTES = {"CRITICAL": 45, "HIGH": 30, "MODERATE": 15, "LOW": 10}
ENGAGEMENT_COLUMNS = ["vle_total_clicks", "vle_clicks_last_7_days", "vle_clicks_last_14_days", "vle_forum_clicks",
                      "vle_resource_clicks", "vle_quiz_clicks"]


def _add_clicks(row: Dict, extra: float, channel: str = None) -> None:
    for column in ("vle_total_clicks", "vle_clicks_last_7_days", "vle_clicks_last_14_days"):
        row[column] = float(row[column] or 0) + extra
    if channel:
        row[channel] = float(row[channel] or 0) + extra


def _reconnect(row):
    row["vle_days_since_last_activity"] = 0.0
    row["vle_active_days"] = float(row["vle_active_days"] or 0) + 1
    _add_clicks(row, 15)


def _steady_week(row):
    row["vle_active_days"] = float(row["vle_active_days"] or 0) + 4
    row["vle_days_since_last_activity"] = 0.0
    _add_clicks(row, 60)


def _forum(row):
    _add_clicks(row, 30, "vle_forum_clicks")
    row["vle_activity_type_diversity"] = float(row["vle_activity_type_diversity"] or 0) + 1


def _quiz(row):
    _add_clicks(row, 40, "vle_quiz_clicks")
    row["vle_activity_type_diversity"] = float(row["vle_activity_type_diversity"] or 0) + 1


def _resources(row):
    _add_clicks(row, 25, "vle_resource_clicks")


def _submit(row):
    count = float(row["asm_submission_count"] or 0)
    row["asm_submission_count"] = count + 1
    if row["asm_mean_score"] is None or pd.isna(row["asm_mean_score"]):
        row["asm_mean_score"] = 60.0
    if row["asm_average_delay"] is None or pd.isna(row["asm_average_delay"]):
        row["asm_average_delay"] = 0.0


def _tutor(row):
    row["asm_mean_score"] = min(100.0, float(row["asm_mean_score"]) + 10)


def _on_time(row):
    row["asm_average_delay"] = min(float(row["asm_average_delay"]), -1.0)


def _has_score(row) -> bool:
    return row["asm_mean_score"] is not None and not pd.isna(row["asm_mean_score"]) and float(row["asm_mean_score"]) <= 90


def _is_late(row) -> bool:
    return row["asm_average_delay"] is not None and not pd.isna(row["asm_average_delay"]) and float(row["asm_average_delay"]) > 0


def _inactive(row) -> bool:
    days = row["vle_days_since_last_activity"]
    return days is None or pd.isna(days) or float(days) >= 2


@dataclass(frozen=True)
class Lever:
    id: str
    title: str
    owner: str
    effort: int
    apply: Callable[[Dict], None]
    eligible: Callable[[Dict], bool] = lambda row: True


LEVERS: Sequence[Lever] = (
    Lever("reconnect", "Log back in and resume where they stopped", "Student, nudged by advisor", 1, _reconnect, _inactive),
    Lever("on_time", "Agree a plan to submit on or before the deadline", "Advisor", 1, _on_time, _is_late),
    Lever("resources", "Work through this week's course materials", "Student", 1, _resources),
    Lever("forum", "Post in the course forum or join a study group", "Student, peer mentor", 1, _forum),
    Lever("steady_week", "Study on four more days over the next week", "Student, advisor check-in", 2, _steady_week),
    Lever("quiz", "Complete the practice quizzes", "Student", 2, _quiz),
    Lever("submit", "Submit the next assessment", "Student, tutor support", 3, _submit),
    Lever("tutor", "Tutor session aimed at +10 marks on the next assessment", "Tutor", 3, _tutor, _has_score),
)


def _predict(rows: List[Dict]) -> np.ndarray:
    frame = pd.DataFrame(rows, columns=PREDICTIVE_FEATURES)
    for column in frame.columns:
        if column not in ("highest_education", "code_module", "code_presentation"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return inference_service.pipeline.predict_proba(frame)[:, 1]


def _clean(row: Dict) -> Dict:
    return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in row.items()}


def rescue_plans(students: List[Dict], target: float = ALERT_THRESHOLD, max_steps: int = MAX_STEPS) -> List[dict]:
    """Greedy, vectorised across students: one model call per step for the whole batch."""
    current = [dict(s) for s in students]
    start = _predict(current)
    probability = start.copy()
    chosen: List[List[dict]] = [[] for _ in students]
    used: List[set] = [set() for _ in students]
    for _ in range(max_steps):
        candidates, owners = [], []
        for index, row in enumerate(current):
            if probability[index] < target:
                continue
            for lever in LEVERS:
                if lever.id in used[index] or not lever.eligible(row):
                    continue
                moved = dict(row)
                lever.apply(moved)
                candidates.append(moved)
                owners.append((index, lever))
        if not candidates:
            break
        predictions = _predict(candidates)
        best: Dict[int, tuple] = {}
        for (index, lever), p in zip(owners, predictions):
            gain = (probability[index] - p) / lever.effort
            if gain > 1e-4 and (index not in best or gain > best[index][0]):
                best[index] = (gain, lever, p)
        if not best:
            break
        for index, (_, lever, p) in best.items():
            lever.apply(current[index])
            used[index].add(lever.id)
            chosen[index].append({"lever": lever, "probability": float(p)})
            probability[index] = p

    plans = []
    for index, student in enumerate(students):
        steps = _prune([s["lever"] for s in chosen[index]], student, target)
        trail, p = [], float(start[index])
        replay = dict(student)
        for lever in steps:
            lever.apply(replay)
            after = float(_predict([replay])[0])
            trail.append({"id": lever.id, "action": lever.title, "owner": lever.owner, "effort": lever.effort,
                          "risk_before": p, "risk_after": after, "risk_change": after - p})
            p = after
        changes = [{"feature": k, "label": feature_label(k), "from": _clean(student)[k], "to": _clean(replay)[k]}
                   for k in student if _clean(student)[k] != _clean(replay)[k]]
        plans.append({"start_probability": float(start[index]), "end_probability": p, "target": target,
                      "reaches_target": p < target, "already_below_target": float(start[index]) < target,
                      "total_effort": sum(s["effort"] for s in trail), "steps": trail, "feature_changes": changes})
    return plans


def _prune(levers: List[Lever], student: Dict, target: float) -> List[Lever]:
    """Drop any step the plan can reach the target without, so the plan stays minimal."""
    keep = list(levers)
    if not keep:
        return keep

    def outcome(sequence):
        row = dict(student)
        for lever in sequence:
            lever.apply(row)
        return float(_predict([row])[0])

    if outcome(keep) >= target:
        return keep
    for lever in sorted(levers, key=lambda l: -l.effort):
        trial = [l for l in keep if l is not lever]
        if trial and outcome(trial) < target:
            keep = trial
    return keep


def plan_triage(students: List[Dict], references: List[str], advisor_hours: float, response_rate: float = 0.6,
                min_risk: float = 0.3, tier_of: Callable[[float], str] = None) -> dict:
    probabilities = _predict(students)
    order = [i for i in np.argsort(-probabilities) if probabilities[i] >= min_risk][:300]
    if not order:
        return {"budget_minutes": advisor_hours * 60, "selected": [], "candidates": 0, "used_minutes": 0, "expected_saved": 0.0,
                "naive_expected_saved": 0.0, "uplift_vs_naive": 0.0}
    subset = [students[i] for i in order]
    plans = rescue_plans(subset, target=0.0, max_steps=TRIAGE_STEPS)
    options = []
    for position, plan in zip(order, plans):
        p_before = float(probabilities[position])
        tier = tier_of(p_before) if tier_of else ("CRITICAL" if p_before >= 0.5 else "HIGH")
        minutes = TIER_MINUTES.get(tier, 20)
        value = max(0.0, p_before - plan["end_probability"]) * response_rate
        options.append({"reference": references[position], "risk": p_before, "risk_after_plan": plan["end_probability"], "tier": tier,
                        "minutes": minutes, "expected_saved": value, "actions": [s["action"] for s in plan["steps"]]})
    budget = advisor_hours * 60
    selected, used = [], 0
    for option in sorted(options, key=lambda o: -o["expected_saved"] / o["minutes"]):
        if used + option["minutes"] <= budget and option["expected_saved"] > 0:
            selected.append(option)
            used += option["minutes"]
    naive_value, naive_used = 0.0, 0
    for option in options:
        if naive_used + option["minutes"] <= budget:
            naive_value += option["expected_saved"]
            naive_used += option["minutes"]
    expected = sum(o["expected_saved"] for o in selected)
    return {"budget_minutes": budget, "used_minutes": used, "candidates": len(options), "response_rate": response_rate,
            "expected_saved": expected, "naive_expected_saved": naive_value, "uplift_vs_naive": expected - naive_value, "selected": selected}


SCENARIOS = {
    "lms_outage": {"label": "LMS outage", "description": "A week offline: clicks fall 60 %, active days halve, last activity moves 7 days back."},
    "exam_slump": {"label": "Exam slump", "description": "Scores drop 12 marks and students near the pass line fail one more assessment."},
    "late_wave": {"label": "Deadline crunch", "description": "Everyone submits 5 days later than before."},
    "semester_break": {"label": "Break slowdown", "description": "No clicks in the last 7 days, and last activity moves 7 days back."},
    "engagement_drive": {"label": "Engagement drive", "description": "A successful campaign: clicks up 40 % and three more active days."},
}


def _apply_shock(frame: pd.DataFrame, scenario: str, engagement: float, score_shift: float, delay_shift: float) -> pd.DataFrame:
    out = frame.copy()
    if scenario == "lms_outage":
        out[ENGAGEMENT_COLUMNS] = out[ENGAGEMENT_COLUMNS] * 0.4
        out["vle_active_days"] = out["vle_active_days"] * 0.5
        out["vle_days_since_last_activity"] = out["vle_days_since_last_activity"] + 7
    elif scenario == "exam_slump":
        out["asm_mean_score"] = (out["asm_mean_score"] - 12).clip(lower=0)
        out["asm_failed_count"] = out["asm_failed_count"] + (out["asm_mean_score"] < 52).astype(float)
    elif scenario == "late_wave":
        out["asm_average_delay"] = out["asm_average_delay"] + 5
    elif scenario == "semester_break":
        out["vle_clicks_last_7_days"] = 0.0
        out["vle_days_since_last_activity"] = out["vle_days_since_last_activity"] + 7
    elif scenario == "engagement_drive":
        out[ENGAGEMENT_COLUMNS] = out[ENGAGEMENT_COLUMNS] * 1.4
        out["vle_active_days"] = out["vle_active_days"] + 3
    if engagement != 1.0:
        out[ENGAGEMENT_COLUMNS] = out[ENGAGEMENT_COLUMNS] * engagement
    if score_shift:
        out["asm_mean_score"] = (out["asm_mean_score"] + score_shift).clip(0, 100)
    if delay_shift:
        out["asm_average_delay"] = out["asm_average_delay"] + delay_shift
    return out


def stress_test(students: List[Dict], scenario: str, references: List[str], engagement: float = 1.0, score_shift: float = 0.0,
                delay_shift: float = 0.0, threshold: float = ALERT_THRESHOLD) -> dict:
    base = pd.DataFrame(students)
    for column in base.columns:
        if column not in ("highest_education", "code_module", "code_presentation"):
            base[column] = pd.to_numeric(base[column], errors="coerce")
    before = _predict(base.astype(object).where(base.notna(), None).to_dict(orient="records"))
    shocked = _apply_shock(base, scenario, engagement, score_shift, delay_shift)
    after = _predict(shocked.astype(object).where(shocked.notna(), None).to_dict(orient="records"))
    newly = np.where((before < threshold) & (after >= threshold))[0]
    recovered = np.where((before >= threshold) & (after < threshold))[0]
    bins = np.linspace(0, 1, 11)
    ranked = newly[np.argsort(-(after[newly] - before[newly]))][:15]
    return {
        "scenario": scenario, "count": len(students), "threshold": threshold,
        "mean_before": float(before.mean()), "mean_after": float(after.mean()),
        "alerts_before": int((before >= threshold).sum()), "alerts_after": int((after >= threshold).sum()),
        "newly_at_risk": int(len(newly)), "recovered": int(len(recovered)),
        "histogram_before": np.histogram(before, bins)[0].tolist(), "histogram_after": np.histogram(after, bins)[0].tolist(),
        "most_exposed": [{"reference": references[i], "before": float(before[i]), "after": float(after[i])} for i in ranked],
    }
