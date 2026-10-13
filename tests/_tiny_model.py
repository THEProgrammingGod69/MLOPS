"""Tiny stand-in model for tests that must run without the DVC/gitignored artifacts.

Builds the exact production pipeline structure (repo tree preprocessor + XGBClassifier)
on a few hundred synthetic rows in well under a second.
"""
import os
import tempfile

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from src.api.feature_catalog import CATEGORICAL_FEATURES, COURSE_CATALOG, EDUCATION_LEVELS
from src.data.split_dataset import build_tree_preprocessor
from src.models.train_baselines import PREDICTIVE_FEATURES

NUMERIC = [f for f in PREDICTIVE_FEATURES if f not in CATEGORICAL_FEATURES]


def synthetic_frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    courses = [(m, p) for m, ps in COURSE_CATALOG.items() for p in ps]
    picks = rng.integers(0, len(courses), n)
    df = pd.DataFrame({f: rng.gamma(2.0, 20.0, n).round() for f in NUMERIC})
    df["highest_education"] = rng.choice(EDUCATION_LEVELS, n)
    df["code_module"] = [courses[i][0] for i in picks]
    df["code_presentation"] = [courses[i][1] for i in picks]
    df["module_presentation_length"] = [COURSE_CATALOG[m][p] for m, p in zip(df["code_module"], df["code_presentation"])]
    df.loc[rng.random(n) < 0.25, "asm_mean_score"] = np.nan
    df.loc[rng.random(n) < 0.8, "asm_score_std"] = np.nan
    return df[PREDICTIVE_FEATURES]


def build_tiny_pipeline(directory: str = None) -> str:
    """Train and pickle a tiny pipeline; returns its path."""
    directory = directory or tempfile.mkdtemp(prefix="tiny_model_")
    df = synthetic_frame()
    y = ((df["vle_total_clicks"] < 35) | df["asm_mean_score"].isna()).astype(int)
    pipeline = Pipeline([
        ("preprocessor", build_tree_preprocessor(NUMERIC, CATEGORICAL_FEATURES)),
        ("classifier", XGBClassifier(n_estimators=20, max_depth=3, learning_rate=0.3,
                                     eval_metric="logloss", random_state=0, n_jobs=1)),
    ])
    pipeline.fit(df, y)
    path = os.path.join(directory, "xgb_pipeline.pkl")
    joblib.dump(pipeline, path)
    return path
