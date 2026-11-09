"""Universal data adapter: fit any institution's export to the model's 21 inputs.

The model was trained on Open University (OULAD) day-28 data. A college in Pune has
CGPA out of 10 and attendance percentages; a community college has GPA out of 4 and
Canvas page views. The adapter works in four stages:

1. **Profile** each column: numeric, percentage, fraction, date, letter grade, category.
2. **Match** columns to model features one-to-one (Hungarian assignment over a name,
   type and value-plausibility score).
3. **Convert** values. Same-unit columns are rescaled. Columns measuring a related
   behaviour on another scale go through *percentile transport*: a student at their own
   cohort's 30th percentile lands at the 30th percentile of the training distribution.
   Features nobody recorded inherit the student's engagement percentile from the signals
   that do exist, instead of a flat median.
4. **Disclose**. The Institution Fit Score weights each input by its SHAP importance and
   by how it was obtained. If the file holds real outcomes, the raw scores are validated
   against them (AUC) and recalibrated with Platt scaling.

Nothing here makes the model valid for another institution by itself; the fit score and
local validation exist to say how far the result can be trusted.
"""
import io
import json
import os
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from src.adapter.vocabulary import (EDUCATION_RULES, GENDER_VALUES, LETTER_GRADES, NEGATIVE_OUTCOMES, POSITIVE_OUTCOMES,
                                    RETAINED_COLUMNS, ROLE_COLUMNS, TARGETS)
from src.api.feature_catalog import COURSE_CATALOG, base_feature, feature_label
from src.api.settings import settings
from src.models.train_baselines import PREDICTIVE_FEATURES

MIN_MATCH = 0.72
UNIT_PSI_LIMIT = 0.5
UNIT_GUARDED = ("count", "activity", "days_0_28", "diversity")
COURSE_IDENTITY = ("code_module", "code_presentation", "module_presentation_length")
UNSEEN = "UNSEEN"
QUANTILES = np.array([0.0, 0.25, 0.5, 0.75, 0.95, 1.0])
QUALITY = {"direct": 1.0, "scaled": 0.9, "derived": 0.85, "proxy": 0.6, "rule": 0.45, "latent": 0.35,
           "native_missing": 0.2, "default": 0.1}
ORIGIN_TEXT = {
    "direct": "Same measure, same units", "scaled": "Same measure, rescaled", "derived": "Computed from dates",
    "proxy": "Related measure, percentile-transported", "rule": "Inferred from other mapped columns",
    "latent": "Not recorded: inferred from the student's engagement percentile",
    "native_missing": "Not recorded: model's own missing-value path", "default": "Not recorded: neutral training value",
}
DEFAULTS = {"num_of_prev_attempts": 0, "studied_credits": 60, "registration_day": -57, "module_presentation_length": 262,
            "highest_education": "A Level or Equivalent", "code_module": UNSEEN, "code_presentation": UNSEEN}
LATENT_FEATURES = ["vle_total_clicks", "vle_active_days", "vle_clicks_last_7_days", "vle_clicks_last_14_days",
                   "vle_forum_clicks", "vle_resource_clicks", "vle_quiz_clicks", "vle_activity_type_diversity"]
NATIVE_MISSING = {"asm_score_std", "asm_average_delay", "asm_mean_score", "vle_days_since_last_activity"}
TRANSFORMS = {
    "education": ["education"], "module": ["module"], "presentation": ["presentation"],
    "count": ["as_is", "percentile"], "score": ["score_100", "percentile"], "spread": ["as_is"],
    "delay": ["as_is", "percentile"], "activity": ["as_is", "percentile"], "days_0_28": ["as_is", "percentile"],
    "days_since": ["as_is", "percentile", "days_since_date"], "diversity": ["as_is", "percentile"],
    "day_offset": ["as_is", "days_from_start"], "duration_days": ["as_is", "weeks_to_days", "months_to_days"],
}


# ------------------------------------------------------------------------------------ reading
def read_table(content: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        return pd.read_excel(io.BytesIO(content))
    if name.endswith(".json"):
        payload = json.loads(content.decode("utf-8-sig"))
        if isinstance(payload, dict):
            lists = [v for v in payload.values() if isinstance(v, list)]
            payload = lists[0] if lists else [payload]
        return pd.json_normalize(payload)
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    first_line = text.splitlines()[0] if text else ""
    counts = {d: first_line.count(d) for d in (",", ";", "\t", "|")}
    separator = max(counts, key=counts.get)
    if counts[separator] == 0:
        raise ValueError("Could not find a column separator in this file.")
    return pd.read_csv(io.StringIO(text), sep=separator, skipinitialspace=True)


def normalise(name: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name))
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", spaced.lower()).split())


def _parse_numeric(series: pd.Series) -> Tuple[pd.Series, Optional[str]]:
    if pd.api.types.is_bool_dtype(series):
        return series.astype(float), None
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").astype(float), None
    text = series.astype("string").str.strip()
    fraction = text.str.extract(r"^(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$")
    if fraction[0].notna().mean() > 0.7:
        return pd.to_numeric(fraction[0], errors="coerce") / pd.to_numeric(fraction[1], errors="coerce") * 100, "fraction"
    is_percent = text.str.endswith("%", na=False).mean() > 0.5
    cleaned = text.str.replace(r"[%,\s]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce").astype(float), "percent" if is_percent else None


def profile_column(series: pd.Series) -> dict:
    present = series.dropna()
    n = max(len(present), 1)
    numeric, note = _parse_numeric(series)
    numeric_share = float(numeric.notna().sum() / n)
    kind = "category"
    extra: dict = {}
    if numeric_share >= 0.8:
        kind = "percent" if note == "percent" else "fraction" if note == "fraction" else "number"
        values = numeric.dropna()
        if len(values):
            extra = {"min": float(values.min()), "max": float(values.max()), "mean": round(float(values.mean()), 3)}
    else:
        text = present.astype(str).str.strip()
        if text.str.upper().isin(LETTER_GRADES).mean() > 0.8 and text.nunique() <= 15:
            kind = "letter_grade"
        elif text.str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", regex=True).mean() > 0.8:
            kind = "date"
    return {"name": str(series.name), "kind": kind, "missing_rate": round(float(series.isna().mean()), 4),
            "unique": int(present.nunique()), "samples": [str(v) for v in present.head(3).tolist()], **extra}


# ------------------------------------------------------------------------------------ matching
def name_score(column: str, candidates: List[str]) -> float:
    target = normalise(column)
    best = 0.0
    tokens = set(target.split())
    for candidate in candidates:
        if target == candidate:
            return 1.0
        cand_tokens = set(candidate.split())
        if tokens == cand_tokens:
            best = max(best, 0.97)
            continue
        if cand_tokens and cand_tokens <= tokens and len(cand_tokens) >= max(1, len(tokens) - 1):
            best = max(best, 0.88)
        best = max(best, SequenceMatcher(None, target, candidate).ratio() * 0.92)
    return best


def _plausible(target: str, spec: dict, profile: dict) -> float:
    kind = spec["kind"]
    column_kind = profile["kind"]
    if kind in ("education", "module", "presentation"):
        return 1.0 if column_kind in ("category", "number") else 0.5
    if column_kind == "date":
        return 1.0 if spec.get("date") else 0.0
    if kind == "score":
        return 1.0 if column_kind in ("number", "percent", "fraction", "letter_grade") else 0.0
    if column_kind in ("category", "letter_grade"):
        return 0.0
    low, high = profile.get("min", 0), profile.get("max", 0)
    if kind == "count" and low < 0:
        return 0.3
    if kind == "days_0_28" and high > 400:
        return 0.3
    return 1.0


def match_columns(frame: pd.DataFrame, profiles: Dict[str, dict]) -> dict:
    columns = list(frame.columns)
    roles: Dict[str, Optional[str]] = {}
    taken = set()
    for role, names in ROLE_COLUMNS.items():
        scored = sorted(((name_score(c, names), c) for c in columns if c not in taken), reverse=True)
        best = scored[0] if scored else (0, None)
        roles[role] = best[1] if best[0] >= 0.9 else None
        if roles[role] is not None:
            taken.add(roles[role])

    free = [c for c in columns if c not in taken]
    features = list(TARGETS)
    scores = np.zeros((len(features), max(len(free), 1)))
    origins: Dict[Tuple[int, int], str] = {}
    for i, feature in enumerate(features):
        spec = TARGETS[feature]
        for j, column in enumerate(free):
            direct = name_score(column, spec["direct"]) if spec["direct"] else 0.0
            proxy = name_score(column, spec["proxy"]) * 0.94 if spec["proxy"] else 0.0
            dated = name_score(column, spec.get("date", [])) if spec.get("date") else 0.0
            value = max(direct, proxy, dated)
            origins[(i, j)] = "date" if value == dated and dated > 0 else "proxy" if value == proxy and proxy > direct else "direct"
            scores[i, j] = value * _plausible(feature, spec, profiles[column])
    mapping: Dict[str, dict] = {}
    if free:
        # Weak matches must not buy a better total: below the bar they count for nothing, and
        # cubing makes one exact match outweigh two middling ones.
        objective = np.where(scores >= MIN_MATCH, scores ** 3, 0.0)
        rows, cols = linear_sum_assignment(-objective)
        assigned = {features[r]: (free[c], float(scores[r, c]), origins[(r, c)]) for r, c in zip(rows, cols)}
    else:
        assigned = {}
    for feature, spec in TARGETS.items():
        column, confidence, origin = assigned.get(feature, (None, 0.0, "direct"))
        if column is None or confidence < MIN_MATCH:
            mapping[feature] = {"column": None, "confidence": 0.0, "transform": None, "origin": None}
            continue
        transform = _default_transform(spec, origin, profiles[column], column)
        if transform == "as_is" and spec["kind"] in UNIT_GUARDED and _unit_mismatch(frame[column], feature):
            transform, origin = "percentile", "proxy"
        mapping[feature] = {"column": column, "confidence": round(confidence, 3), "origin": origin, "transform": transform}
    return {"targets": mapping, "roles": roles}


def _unit_mismatch(series: pd.Series, feature: str) -> bool:
    """Right name, wrong unit: 'Quiz Attempts' of 5 is not 5 quiz clicks. Transport it instead."""
    numeric, note = _parse_numeric(series)
    if note == "fraction":
        return True
    psi = _psi(numeric, feature)
    return psi is not None and psi > UNIT_PSI_LIMIT


def _default_transform(spec: dict, origin: str, profile: dict, column: str) -> str:
    kind = spec["kind"]
    label = normalise(column)
    if kind in ("education", "module", "presentation"):
        return kind
    if origin == "date":
        return "days_since_date" if kind == "days_since" else "days_from_start"
    if kind == "score":
        return "score_100"
    if kind == "duration_days":
        return "months_to_days" if "month" in label else "weeks_to_days" if "week" in label else "as_is"
    return "percentile" if origin == "proxy" else "as_is"


# ------------------------------------------------------------------------------------ reference
def _load_reference() -> Dict[str, np.ndarray]:
    reference = {"registration_day": np.array([-300.0, -100.0, -57.0, -29.0, -10.0, 20.0])}
    path = os.path.join(settings.reports_dir, "eda", "numeric_summary.csv")
    try:
        summary = pd.read_csv(path, index_col=0)
        for name, row in summary.iterrows():
            reference[str(name)] = row[["min", "25%", "50%", "75%", "95%", "max"]].to_numpy(dtype=float)
    except (OSError, KeyError, ValueError):
        pass
    return reference


REFERENCE = _load_reference()


def _load_importance() -> Dict[str, float]:
    path = os.path.join(settings.reports_dir, "explainability", "shap_global_importance.csv")
    weights: Dict[str, float] = {}
    try:
        table = pd.read_csv(path)
        for _, row in table.iterrows():
            feature = base_feature(str(row["feature"]))
            if feature:
                weights[feature] = weights.get(feature, 0.0) + float(row["mean_abs_shap"])
    except (OSError, KeyError, ValueError):
        pass
    return {f: weights.get(f, 0.0) + 1e-3 for f in PREDICTIVE_FEATURES}


IMPORTANCE = _load_importance()


def percentile_ranks(values: pd.Series) -> pd.Series:
    return values.rank(pct=True, method="average")


def transport(values: pd.Series, feature: str) -> pd.Series:
    """Move values onto the training distribution of ``feature`` by percentile."""
    points = REFERENCE.get(feature)
    if points is None:
        return values
    return pd.Series(np.interp(percentile_ranks(values).fillna(0.5), QUANTILES, points), index=values.index).where(values.notna())


# ------------------------------------------------------------------------------------ transforms
def to_score_100(series: pd.Series) -> Tuple[pd.Series, str]:
    text = series.astype("string").str.strip().str.upper()
    if text.isin(LETTER_GRADES).mean() > 0.6:
        return text.map(LETTER_GRADES).astype(float), "Letter grades converted to percent"
    numeric, note = _parse_numeric(series)
    high = numeric.max()
    if note in ("percent", "fraction") or pd.isna(high) or high > 20:
        return numeric.clip(0, 100), "Already out of 100"
    if high <= 4.3:
        return (numeric / 4.0 * 100).clip(0, 100), "GPA on a 4-point scale, rescaled to 100"
    if high <= 10:
        return (numeric * 10).clip(0, 100), "CGPA on a 10-point scale, rescaled to 100"
    return (numeric * 5).clip(0, 100), "Marks out of 20, rescaled to 100"


def to_education(series: pd.Series) -> pd.Series:
    def convert(value):
        if pd.isna(value):
            return DEFAULTS["highest_education"]
        text = normalise(value)
        tokens = set(text.split())
        for level, keywords in EDUCATION_RULES:
            if any(k == text or (" " in k and k in text) or k in tokens for k in keywords):
                return level
        return DEFAULTS["highest_education"]
    return series.map(convert)


def to_module(series: pd.Series) -> pd.Series:
    known = set(COURSE_CATALOG)
    return series.astype("string").str.strip().str.upper().map(lambda v: v if v in known else UNSEEN)


def to_presentation(series: pd.Series) -> pd.Series:
    known = {p for presentations in COURSE_CATALOG.values() for p in presentations}
    return series.astype("string").str.strip().str.upper().map(lambda v: v if v in known else UNSEEN)


def _parse_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=True)


# ------------------------------------------------------------------------------------ application
def adapt(frame: pd.DataFrame, mapping: dict, as_of: Optional[str] = None) -> dict:
    roles = mapping.get("roles", {})
    out = pd.DataFrame(index=frame.index)
    how: Dict[str, dict] = {}
    columns = set(frame.columns)
    reference_date = pd.to_datetime(as_of, errors="coerce") if as_of else pd.NaT
    if pd.isna(reference_date) and roles.get("as_of") in columns:
        reference_date = _parse_dates(frame[roles["as_of"]]).max()
    start_dates = _parse_dates(frame[roles["course_start"]]) if roles.get("course_start") in columns else None

    for feature, spec in TARGETS.items():
        entry = mapping["targets"].get(feature) or {}
        column = entry.get("column")
        if column not in columns:
            continue
        transform = entry.get("transform") or "as_is"
        series = frame[column]
        origin, note = ("proxy" if transform == "percentile" else "direct"), None
        if transform == "education":
            out[feature], origin = to_education(series), "direct"
        elif transform == "module":
            out[feature] = to_module(series)
            origin, note = "default", "Course codes are outside the training catalogue, so the course effect is neutralised"
            if (out[feature] != UNSEEN).mean() > 0.5:
                origin, note = "direct", None
        elif transform == "presentation":
            out[feature] = to_presentation(series)
            origin, note = "default", "Terms are outside the training catalogue, so the term effect is neutralised"
            if (out[feature] != UNSEEN).mean() > 0.5:
                origin, note = "direct", None
        elif transform == "score_100":
            out[feature], note = to_score_100(series)
            origin = "direct" if note == "Already out of 100" else "scaled"
        elif transform == "days_since_date":
            dates = _parse_dates(series)
            anchor = reference_date if not pd.isna(reference_date) else dates.max()
            out[feature] = (anchor - dates).dt.days.clip(lower=0).astype(float)
            origin, note = "derived", f"Days from last activity to {pd.Timestamp(anchor).date()}"
        elif transform == "days_from_start":
            dates = _parse_dates(series)
            anchor = start_dates if start_dates is not None else dates.median()
            out[feature] = (dates - anchor).dt.days.astype(float)
            origin, note = "derived", "Days relative to the course start"
        else:
            numeric, _ = _parse_numeric(series)
            if transform == "percentile":
                numeric = transport(numeric, feature)
            elif transform == "weeks_to_days":
                numeric, origin, note = numeric * 7, "scaled", "Weeks converted to days"
            elif transform == "months_to_days":
                numeric, origin, note = numeric * 30, "scaled", "Months converted to days"
            out[feature] = numeric
        how[feature] = {"column": column, "transform": transform, "origin": origin, "note": note,
                        "confidence": float(entry.get("confidence") or 1.0)}

    # Students' engagement percentile from whichever engagement signals were supplied.
    engagement_inputs = [percentile_ranks(pd.to_numeric(out[f], errors="coerce")) for f in LATENT_FEATURES if f in out]
    if "vle_days_since_last_activity" in out:
        engagement_inputs.append(1 - percentile_ranks(pd.to_numeric(out["vle_days_since_last_activity"], errors="coerce")))
    latent = pd.concat(engagement_inputs, axis=1).mean(axis=1).fillna(0.5) if engagement_inputs else None

    for feature in PREDICTIVE_FEATURES:
        if feature in out:
            continue
        if feature in LATENT_FEATURES and latent is not None:
            out[feature] = np.interp(latent, QUANTILES, REFERENCE[feature])
            how[feature] = {"column": None, "transform": "latent", "origin": "latent", "note": None, "confidence": 1.0}
        elif feature == "vle_days_since_last_activity" and latent is not None:
            out[feature] = np.interp(1 - latent, QUANTILES, REFERENCE[feature])
            how[feature] = {"column": None, "transform": "latent", "origin": "latent", "note": None, "confidence": 1.0}
        elif feature == "asm_submission_count" and "asm_mean_score" in out:
            out[feature] = pd.to_numeric(out["asm_mean_score"], errors="coerce").notna().astype(float)
            how[feature] = {"column": None, "transform": "rule", "origin": "rule", "note": "One submission where a score exists", "confidence": 1.0}
        elif feature == "asm_failed_count" and "asm_mean_score" in out:
            out[feature] = (pd.to_numeric(out["asm_mean_score"], errors="coerce") < 40).astype(float)
            how[feature] = {"column": None, "transform": "rule", "origin": "rule", "note": "Counted as failed below 40 %", "confidence": 1.0}
        elif feature in NATIVE_MISSING:
            out[feature] = np.nan
            how[feature] = {"column": None, "transform": "missing", "origin": "native_missing", "note": None, "confidence": 1.0}
        else:
            out[feature] = DEFAULTS.get(feature, 0)
            how[feature] = {"column": None, "transform": "default", "origin": "default", "note": None, "confidence": 1.0}

    _enforce_consistency(out)
    gender = None
    if roles.get("gender") in columns:
        gender = frame[roles["gender"]].astype("string").str.strip().str.lower().map(GENDER_VALUES)
    identifiers = frame[roles["student_id"]].astype("string") if roles.get("student_id") in columns else None
    return {"features": out[PREDICTIVE_FEATURES], "how": how, "gender": gender, "identifiers": identifiers}


def _enforce_consistency(out: pd.DataFrame) -> None:
    counts = ["num_of_prev_attempts", "studied_credits", "asm_submission_count", "asm_failed_count", "vle_total_clicks", "vle_active_days",
              "vle_clicks_last_7_days", "vle_clicks_last_14_days", "vle_forum_clicks", "vle_resource_clicks", "vle_quiz_clicks", "vle_activity_type_diversity"]
    for column in counts + ["module_presentation_length", "vle_days_since_last_activity", "asm_score_std"]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    for column in counts:
        median = REFERENCE.get(column, np.array([0, 0, 0]))[2]
        out[column] = out[column].fillna(median).clip(lower=0)
    out["vle_clicks_last_14_days"] = out[["vle_clicks_last_14_days", "vle_clicks_last_7_days"]].max(axis=1)
    out["vle_total_clicks"] = out[["vle_total_clicks", "vle_clicks_last_14_days"]].max(axis=1)
    out["vle_days_since_last_activity"] = out["vle_days_since_last_activity"].clip(lower=0)
    out["asm_score_std"] = out["asm_score_std"].clip(lower=0)
    out["asm_failed_count"] = out[["asm_failed_count", "asm_submission_count"]].min(axis=1)
    for column in ("num_of_prev_attempts", "studied_credits", "registration_day", "module_presentation_length"):
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(DEFAULTS[column]).round()
    out["module_presentation_length"] = out["module_presentation_length"].clip(lower=1)


# ------------------------------------------------------------------------------------ disclosure
def _psi(values: pd.Series, feature: str) -> Optional[float]:
    points = REFERENCE.get(feature)
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if points is None or len(clean) < 30:
        return None
    edges = np.unique(points[1:-1])
    expected = np.diff(np.concatenate(([0.0], np.interp(edges, points, QUANTILES), [1.0])))
    observed = np.bincount(np.searchsorted(edges, clean.to_numpy(), side="right"), minlength=len(edges) + 1) / len(clean)
    e, o = np.clip(expected, 1e-4, None), np.clip(observed, 1e-4, None)
    return float(np.sum((o - e) * np.log(o / e)))


def fit_report(adapted: dict) -> dict:
    how = adapted["how"]
    features = adapted["features"]
    # Another institution can never share OULAD's course codes, so a neutralised course effect
    # is disclosed in the table but does not count against the data the institution supplied.
    scored = [f for f in PREDICTIVE_FEATURES if not (f in COURSE_IDENTITY and how[f]["origin"] == "default")]
    total = sum(IMPORTANCE[f] for f in scored)
    rows, achieved = [], 0.0
    for feature in PREDICTIVE_FEATURES:
        info = how[feature]
        quality = QUALITY[info["origin"]] * min(1.0, 0.6 + 0.4 * info["confidence"])
        weight = IMPORTANCE[feature] / total if feature in scored else 0.0
        achieved += weight * quality
        psi = _psi(features[feature], feature) if info["origin"] in ("direct", "scaled", "derived") else None
        rows.append({"feature": feature, "label": feature_label(feature), "column": info["column"], "transform": info["transform"],
                     "origin": info["origin"], "origin_text": ORIGIN_TEXT[info["origin"]], "note": info["note"],
                     "confidence": info["confidence"], "importance": round(weight, 4), "quality": round(quality, 3),
                     "psi": None if psi is None else round(psi, 3)})
    shifted = [r for r in rows if r["psi"] is not None and r["psi"] > 0.25]
    penalty = min(15.0, sum(min(r["psi"], 1.0) * r["importance"] * 60 for r in shifted))
    score = max(0.0, min(100.0, achieved * 100 - penalty))
    verdict = "strong" if score >= 70 else "caution" if score >= 45 else "indicative"
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["origin"]] = counts.get(row["origin"], 0) + 1
    advice = {
        "strong": "Most important inputs were measured directly. Probabilities are usable, ideally after local validation.",
        "caution": "Several important inputs are proxies or inferred. Use the cohort ranking first and treat the probability as approximate.",
        "indicative": "Too little of what the model relies on is present. Treat results as a rough ranking and collect more signals before acting.",
    }[verdict]
    return {"score": round(score, 1), "verdict": verdict, "advice": advice, "origin_counts": counts,
            "drift_penalty": round(penalty, 1), "features": sorted(rows, key=lambda r: -r["importance"])}


def outcomes_from(frame: pd.DataFrame, column: Optional[str]) -> Optional[pd.Series]:
    if not column or column not in frame.columns:
        return None
    text = frame[column].astype("string").str.strip().str.lower()
    labels = pd.Series(np.nan, index=frame.index, dtype=float)
    labels[text.isin(POSITIVE_OUTCOMES)] = 1.0
    labels[text.isin(NEGATIVE_OUTCOMES)] = 0.0
    if normalise(column) in RETAINED_COLUMNS:
        labels = 1.0 - labels
    return labels if labels.notna().mean() >= 0.5 else None


def local_validation(probabilities: np.ndarray, labels: Optional[pd.Series]) -> dict:
    """Validate raw scores against real outcomes and fit Platt scaling when there are enough."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    if labels is None:
        return {"available": False, "calibrated": None, "reason": "No outcome column in this file."}
    mask = labels.notna().to_numpy()
    y = labels.to_numpy()[mask].astype(int)
    p = np.clip(probabilities[mask], 1e-6, 1 - 1e-6)
    if len(y) < 30 or y.min() == y.max() or min(np.bincount(y)) < 5:
        return {"available": False, "calibrated": None, "reason": "Needs at least 30 rows with 5 or more of each outcome."}
    logit = np.log(p / (1 - p)).reshape(-1, 1)
    model = LogisticRegression(C=1e6).fit(logit, y)
    every = np.clip(probabilities, 1e-6, 1 - 1e-6)
    calibrated = model.predict_proba(np.log(every / (1 - every)).reshape(-1, 1))[:, 1]
    return {"available": True, "n": int(len(y)), "base_rate": round(float(y.mean()), 4), "auc": round(float(roc_auc_score(y, p)), 4),
            "brier_raw": round(float(brier_score_loss(y, p)), 4),
            "brier_calibrated": round(float(brier_score_loss(y, calibrated[mask])), 4),
            "calibrated": calibrated, "reason": None}
