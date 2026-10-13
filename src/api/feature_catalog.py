"""Human-facing metadata for the 21 Day-28 predictive features.

The catalog drives the web UI (form layout, labels, ranges, defaults), the readable
names shown next to SHAP contributions, and the course lookup that auto-fills the
presentation length. ``PREDICTIVE_FEATURES`` from the training code stays the single
source of truth for feature order; ``validate_catalog`` asserts the two never diverge.
"""
from typing import Dict, List, Optional

from src.models.train_baselines import PREDICTIVE_FEATURES

CATEGORICAL_FEATURES = ["highest_education", "code_module", "code_presentation"]
NUMERIC_FEATURES = [f for f in PREDICTIVE_FEATURES if f not in CATEGORICAL_FEATURES]

# OULAD courses.csv: (module, presentation) -> module_presentation_length in days.
COURSE_CATALOG: Dict[str, Dict[str, int]] = {
    "AAA": {"2013J": 268, "2014J": 269},
    "BBB": {"2013B": 240, "2013J": 268, "2014B": 234, "2014J": 262},
    "CCC": {"2014B": 241, "2014J": 269},
    "DDD": {"2013B": 240, "2013J": 261, "2014B": 241, "2014J": 262},
    "EEE": {"2013J": 268, "2014B": 241, "2014J": 269},
    "FFF": {"2013B": 240, "2013J": 268, "2014B": 241, "2014J": 269},
    "GGG": {"2013J": 261, "2014B": 241, "2014J": 269},
}

EDUCATION_LEVELS = [
    "A Level or Equivalent",
    "Lower Than A Level",
    "HE Qualification",
    "Post Graduate Qualification",
    "No Formal quals",
]

FEATURE_GROUPS = [
    {"id": "enrollment", "label": "Enrollment & background",
     "description": "Registration context known before the module starts."},
    {"id": "assessment", "label": "Assessment performance",
     "description": "Submissions and scores up to day 28."},
    {"id": "engagement", "label": "VLE engagement",
     "description": "Virtual Learning Environment activity up to day 28."},
]


def _num(name, label, group, description, *, minimum=None, maximum=None, step=1.0,
         default=None, unit=None, nullable=False, integer=False, null_label=None):
    return {
        "name": name, "label": label, "group": group, "description": description,
        "kind": "integer" if integer else "number", "min": minimum, "max": maximum,
        "step": step, "default": default, "unit": unit, "nullable": nullable,
        "null_label": null_label, "options": None,
    }


def _cat(name, label, group, description, options, default):
    return {
        "name": name, "label": label, "group": group, "description": description,
        "kind": "category", "min": None, "max": None, "step": None, "default": default,
        "unit": None, "nullable": False, "null_label": None, "options": options,
    }


# Defaults are the training-set medians from reports/eda/numeric_summary.csv where available.
FEATURE_CATALOG: List[dict] = [
    _cat("highest_education", "Highest education", "enrollment",
         "Highest qualification on entry.", EDUCATION_LEVELS, "A Level or Equivalent"),
    _num("num_of_prev_attempts", "Previous attempts", "enrollment",
         "Times the student previously attempted this module.", minimum=0, maximum=10,
         default=0, integer=True),
    _num("studied_credits", "Studied credits", "enrollment",
         "Total credits the student is studying this presentation.", minimum=0, maximum=700,
         step=15, default=60, integer=True),
    _num("registration_day", "Registration day", "enrollment",
         "Registration date relative to module start (negative = before start).",
         minimum=-400, maximum=28, default=-30, unit="days", integer=True),
    _cat("code_module", "Module", "enrollment", "OULAD module code.",
         sorted(COURSE_CATALOG), "FFF"),
    _cat("code_presentation", "Presentation", "enrollment",
         "Presentation code (year + B = February, J = October start).",
         ["2013B", "2013J", "2014B", "2014J"], "2014J"),
    _num("module_presentation_length", "Presentation length", "enrollment",
         "Length of the module presentation.", minimum=1, maximum=400, default=269,
         unit="days", integer=True),
    _num("asm_submission_count", "Assessments submitted", "assessment",
         "Assessments submitted by day 28.", minimum=0, maximum=20, default=1),
    _num("asm_mean_score", "Mean assessment score", "assessment",
         "Mean score of assessments submitted by day 28.", minimum=0, maximum=100,
         step=0.5, default=78, nullable=True, null_label="No scored submissions yet"),
    _num("asm_score_std", "Score standard deviation", "assessment",
         "Spread of assessment scores (needs two or more scored submissions).", minimum=0,
         maximum=100, step=0.5, default=None, nullable=True,
         null_label="Fewer than two scored submissions"),
    _num("asm_failed_count", "Failed assessments", "assessment",
         "Assessments scored below the pass mark by day 28.", minimum=0, maximum=20, default=0),
    _num("asm_average_delay", "Average submission delay", "assessment",
         "Mean days between deadline and submission (negative = early).", minimum=-300,
         maximum=100, step=0.5, default=-1, unit="days", nullable=True,
         null_label="No submissions yet"),
    _num("vle_total_clicks", "Total VLE clicks", "engagement",
         "All VLE clicks up to day 28.", minimum=0, maximum=20000, default=225),
    _num("vle_active_days", "Active days", "engagement",
         "Distinct days with VLE activity.", minimum=0, maximum=60, default=13, unit="days"),
    _num("vle_days_since_last_activity", "Days since last activity", "engagement",
         "Days between the last VLE activity and day 28.", minimum=0, maximum=60, default=2,
         unit="days", nullable=True, null_label="No VLE activity recorded"),
    _num("vle_clicks_last_7_days", "Clicks, last 7 days", "engagement",
         "VLE clicks between day 21 and day 28.", minimum=0, maximum=10000, default=25),
    _num("vle_clicks_last_14_days", "Clicks, last 14 days", "engagement",
         "VLE clicks between day 14 and day 28.", minimum=0, maximum=10000, default=83),
    _num("vle_forum_clicks", "Forum clicks", "engagement",
         "Clicks on forum activities.", minimum=0, maximum=10000, default=36),
    _num("vle_resource_clicks", "Resource clicks", "engagement",
         "Clicks on standard learning resources.", minimum=0, maximum=10000, default=9),
    _num("vle_quiz_clicks", "Quiz clicks", "engagement",
         "Clicks on quizzes and self-assessments.", minimum=0, maximum=10000, default=0),
    _num("vle_activity_type_diversity", "Activity type diversity", "engagement",
         "Number of distinct VLE activity types used.", minimum=0, maximum=20, default=7),
]

# Behavioural archetypes for the UI's quick-fill presets. They are illustrative inputs,
# not labelled outcomes: the deployed model decides each one's tier.
SAMPLE_PROFILES: List[dict] = [
    {
        "id": "engaged", "label": "Engaged achiever",
        "description": "Early registration, strong scores, daily VLE use.",
        "features": {
            "highest_education": "A Level or Equivalent", "num_of_prev_attempts": 0,
            "studied_credits": 60, "registration_day": -60, "code_module": "BBB",
            "code_presentation": "2014J", "module_presentation_length": 262,
            "asm_submission_count": 2, "asm_mean_score": 88, "asm_score_std": 4,
            "asm_failed_count": 0, "asm_average_delay": -2, "vle_total_clicks": 900,
            "vle_active_days": 26, "vle_days_since_last_activity": 0,
            "vle_clicks_last_7_days": 210, "vle_clicks_last_14_days": 420,
            "vle_forum_clicks": 300, "vle_resource_clicks": 40, "vle_quiz_clicks": 180,
            "vle_activity_type_diversity": 10,
        },
    },
    {
        "id": "steady", "label": "Steady progress",
        "description": "Typical cohort medians across every signal.",
        "features": {
            "highest_education": "Lower Than A Level", "num_of_prev_attempts": 0,
            "studied_credits": 60, "registration_day": -30, "code_module": "FFF",
            "code_presentation": "2014J", "module_presentation_length": 269,
            "asm_submission_count": 1, "asm_mean_score": 72, "asm_score_std": None,
            "asm_failed_count": 0, "asm_average_delay": -1, "vle_total_clicks": 225,
            "vle_active_days": 13, "vle_days_since_last_activity": 2,
            "vle_clicks_last_7_days": 25, "vle_clicks_last_14_days": 83,
            "vle_forum_clicks": 36, "vle_resource_clicks": 9, "vle_quiz_clicks": 0,
            "vle_activity_type_diversity": 7,
        },
    },
    {
        "id": "disengaging", "label": "Disengaging",
        "description": "Late, low-scoring submission and fading activity.",
        "features": {
            "highest_education": "Lower Than A Level", "num_of_prev_attempts": 1,
            "studied_credits": 120, "registration_day": -10, "code_module": "DDD",
            "code_presentation": "2014B", "module_presentation_length": 241,
            "asm_submission_count": 1, "asm_mean_score": 45, "asm_score_std": None,
            "asm_failed_count": 1, "asm_average_delay": 6, "vle_total_clicks": 70,
            "vle_active_days": 4, "vle_days_since_last_activity": 12,
            "vle_clicks_last_7_days": 0, "vle_clicks_last_14_days": 5,
            "vle_forum_clicks": 10, "vle_resource_clicks": 2, "vle_quiz_clicks": 0,
            "vle_activity_type_diversity": 3,
        },
    },
    {
        "id": "silent", "label": "Silent start",
        "description": "No submissions and almost no VLE footprint.",
        "features": {
            "highest_education": "Lower Than A Level", "num_of_prev_attempts": 0,
            "studied_credits": 90, "registration_day": -2, "code_module": "CCC",
            "code_presentation": "2014J", "module_presentation_length": 269,
            "asm_submission_count": 0, "asm_mean_score": None, "asm_score_std": None,
            "asm_failed_count": 0, "asm_average_delay": None, "vle_total_clicks": 12,
            "vle_active_days": 2, "vle_days_since_last_activity": 20,
            "vle_clicks_last_7_days": 0, "vle_clicks_last_14_days": 0,
            "vle_forum_clicks": 2, "vle_resource_clicks": 1, "vle_quiz_clicks": 0,
            "vle_activity_type_diversity": 1,
        },
    },
]

_LABELS = {f["name"]: f["label"] for f in FEATURE_CATALOG}


def validate_catalog() -> None:
    names = [f["name"] for f in FEATURE_CATALOG]
    if names != list(PREDICTIVE_FEATURES):
        raise ValueError("FEATURE_CATALOG must list exactly PREDICTIVE_FEATURES in training order")
    for profile in SAMPLE_PROFILES:
        if set(profile["features"]) != set(PREDICTIVE_FEATURES):
            raise ValueError(f"Sample profile '{profile['id']}' does not cover all features")


def feature_label(name: str) -> str:
    return _LABELS.get(name, name.replace("_", " ").capitalize())


def base_feature(transformed_name: str) -> Optional[str]:
    """Map a ColumnTransformer output name back to its raw input feature.

    ``num__asm_mean_score`` -> ``asm_mean_score``;
    ``num__missingindicator_asm_mean_score`` -> ``asm_mean_score``;
    ``cat__code_module_AAA`` -> ``code_module``.
    """
    name = transformed_name.split("__", 1)[1] if "__" in transformed_name else transformed_name
    if name.startswith("missingindicator_"):
        name = name[len("missingindicator_"):]
    if name in _LABELS:
        return name
    for cat in sorted(CATEGORICAL_FEATURES, key=len, reverse=True):
        if name.startswith(cat + "_"):
            return cat
    return None


def transformed_label(transformed_name: str) -> str:
    """Readable label for one transformed (one-hot / indicator) column."""
    name = transformed_name.split("__", 1)[1] if "__" in transformed_name else transformed_name
    if name.startswith("missingindicator_"):
        return f"{feature_label(name[len('missingindicator_'):])} is missing"
    for cat in sorted(CATEGORICAL_FEATURES, key=len, reverse=True):
        if name.startswith(cat + "_"):
            return f"{feature_label(cat)} = {name[len(cat) + 1:]}"
    return feature_label(name)


def schema_payload() -> dict:
    return {
        "features": FEATURE_CATALOG,
        "groups": FEATURE_GROUPS,
        "course_catalog": COURSE_CATALOG,
        "samples": SAMPLE_PROFILES,
        "sensitive_attribute": {
            "name": "gender", "label": "Gender (optional)", "options": ["M", "F"],
            "description": "Used only by the fairness post-processor; never by the risk model.",
        },
    }


validate_catalog()
