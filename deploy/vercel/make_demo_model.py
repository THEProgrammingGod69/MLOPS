"""Train the DEMO stand-in model at image build time (deploy/vercel only).

The real OULAD-trained artifacts are DVC-tracked and not in git, so the public demo
builds the same sklearn Pipeline (repo preprocessor + XGBClassifier with the repo
hyper-parameters) on synthetic rows. Predictions are illustrative, not the real model.
"""
import os
import sys

import joblib
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.getcwd())
from src.data.split_dataset import build_tree_preprocessor  # noqa: E402
from src.models.train_baselines import PREDICTIVE_FEATURES  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402
from fairlearn.postprocessing import ThresholdOptimizer  # noqa: E402

rng = np.random.default_rng(7)
N = 20000
COURSES = {
    ("AAA", "2013J"): 268, ("AAA", "2014J"): 269, ("BBB", "2013B"): 240, ("BBB", "2013J"): 268,
    ("BBB", "2014B"): 234, ("BBB", "2014J"): 262, ("CCC", "2014B"): 241, ("CCC", "2014J"): 269,
    ("DDD", "2013B"): 240, ("DDD", "2013J"): 261, ("DDD", "2014B"): 241, ("DDD", "2014J"): 262,
    ("EEE", "2013J"): 268, ("EEE", "2014B"): 241, ("EEE", "2014J"): 269, ("FFF", "2013B"): 240,
    ("FFF", "2013J"): 268, ("FFF", "2014B"): 241, ("FFF", "2014J"): 269, ("GGG", "2013J"): 261,
    ("GGG", "2014B"): 241, ("GGG", "2014J"): 269,
}
keys = list(COURSES)
idx = rng.integers(0, len(keys), N)
mod = [keys[i][0] for i in idx]
pres = [keys[i][1] for i in idx]
engagement = rng.gamma(2.0, 1.0, N)  # latent engagement

df = pd.DataFrame({
    "highest_education": rng.choice(
        ["A Level or Equivalent", "Lower Than A Level", "HE Qualification",
         "Post Graduate Qualification", "No Formal quals"], N, p=[0.44, 0.39, 0.15, 0.01, 0.01]),
    "num_of_prev_attempts": rng.choice([0, 1, 2, 3], N, p=[0.87, 0.10, 0.02, 0.01]),
    "studied_credits": rng.choice([30, 60, 90, 120, 150], N, p=[0.15, 0.55, 0.12, 0.13, 0.05]),
    "registration_day": np.round(-np.abs(rng.normal(55, 45, N))).astype(int),
    "code_module": mod,
    "code_presentation": pres,
    "module_presentation_length": [COURSES[(m, p)] for m, p in zip(mod, pres)],
})
df["asm_submission_count"] = np.clip(np.round(engagement * 0.6 + rng.normal(0, 0.4, N)), 0, 6)
score = np.clip(rng.normal(60 + 6 * engagement, 18, N), 0, 100)
df["asm_mean_score"] = np.where(df["asm_submission_count"] > 0, np.round(score, 1), np.nan)
df["asm_score_std"] = np.where(df["asm_submission_count"] > 1, np.round(np.abs(rng.normal(8, 6, N)), 2), np.nan)
df["asm_failed_count"] = np.where(df["asm_mean_score"] < 40, 1.0, 0.0)
df["asm_average_delay"] = np.where(df["asm_submission_count"] > 0, np.round(rng.normal(-3, 6, N), 1), np.nan)
df["vle_total_clicks"] = np.round(engagement * 160 * rng.lognormal(0, 0.5, N))
df["vle_active_days"] = np.clip(np.round(engagement * 6 + rng.normal(0, 3, N)), 0, 54)
df["vle_days_since_last_activity"] = np.clip(np.round(rng.exponential(6 / (engagement + 0.3))), 0, 52)
df["vle_clicks_last_7_days"] = np.round(df["vle_total_clicks"] * rng.uniform(0.05, 0.3, N))
df["vle_clicks_last_14_days"] = np.round(df["vle_clicks_last_7_days"] * rng.uniform(1.5, 3.0, N))
df["vle_forum_clicks"] = np.round(df["vle_total_clicks"] * rng.uniform(0.1, 0.4, N))
df["vle_resource_clicks"] = np.round(df["vle_total_clicks"] * rng.uniform(0.02, 0.08, N))
df["vle_quiz_clicks"] = np.round(df["vle_total_clicks"] * rng.uniform(0.0, 0.3, N))
df["vle_activity_type_diversity"] = np.clip(np.round(engagement * 2.5 + rng.normal(2, 1.5, N)), 0, 14)
gender = rng.choice(["M", "F"], N, p=[0.55, 0.45])

logit = (-1.0 - 0.9 * engagement + 0.012 * (df["studied_credits"] - 60)
         + 1.1 * df["asm_mean_score"].isna() - 0.015 * df["asm_mean_score"].fillna(50).sub(60)
         + 0.08 * df["vle_days_since_last_activity"] + 0.5 * df["num_of_prev_attempts"]
         + 0.4 * (df["highest_education"] == "Lower Than A Level")
         + np.where(df["code_module"].isin(["CCC", "DDD"]), 0.5, 0.0))
y = (rng.uniform(size=N) < 1 / (1 + np.exp(-logit))).astype(int)

cfg = yaml.safe_load(open("configs/model_config.yaml"))["models"]
x = cfg["xgboost"]
num_cols = [f for f in PREDICTIVE_FEATURES if f not in ["highest_education", "code_module", "code_presentation"]]
cat_cols = ["highest_education", "code_module", "code_presentation"]
pipe = Pipeline([
    ("preprocessor", build_tree_preprocessor(num_cols, cat_cols)),
    ("classifier", XGBClassifier(n_estimators=x["n_estimators"], max_depth=x["max_depth"],
                                 learning_rate=x["learning_rate"], subsample=x["subsample"],
                                 colsample_bytree=x["colsample_bytree"], eval_metric=x["eval_metric"],
                                 n_jobs=2, random_state=cfg["random_state"])),
])
X = df[PREDICTIVE_FEATURES]
pipe.fit(X, y)
os.makedirs("models/baseline", exist_ok=True)
os.makedirs("models/mitigated", exist_ok=True)
joblib.dump(pipe, "models/baseline/xgb_pipeline.pkl")

to = ThresholdOptimizer(estimator=pipe, constraints="equalized_odds", predict_method="predict_proba", prefit=False)
to.fit(X, y, sensitive_features=gender)
joblib.dump(to, "models/mitigated/xgb_threshold_optimizer_gender.pkl")

print("demo model trained; positive rate", round(float(y.mean()), 3))
