"""Train exactly the two artifacts the API serves, from the real OULAD splits.

Uses the project's own model definition (``src.models.train_baselines``) and the same
ThresholdOptimizer configuration as ``src.fairness.mitigate``, without the MLflow experiment
grid around them. Metrics are compared against the committed report from the original run,
so a faithful retrain is demonstrated rather than assumed.

Governance (docs/data_split_governance.md): fitting uses ``train.parquet``, as
``train_baselines.py`` does for this artifact. Evaluation uses ``validation.parquet`` only.
The locked test split is deliberately never read here.

Prerequisite: the steps in ``src/data`` have produced ``data/processed/splits/``.

    python scripts/train_served_model.py
"""
import glob
import json
import os
import pickle
import sys

import joblib
import numpy as np
import pandas as pd
import yaml
from fairlearn.metrics import equalized_odds_difference
from fairlearn.postprocessing import ThresholdOptimizer
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score

sys.path.insert(0, os.getcwd())
from src.models.train_baselines import PREDICTIVE_FEATURES, get_models  # noqa: E402

SPLITS = "data/processed/splits"
CATEGORICAL = ("highest_education", "code_module", "code_presentation")
MODEL_PATH = "models/baseline/xgb_pipeline.pkl"
MITIGATED_PATH = "models/mitigated/xgb_threshold_optimizer_gender.pkl"
SENSITIVE = "gender"
FAIRNESS_SEED = 42
ALERT_THRESHOLD = 0.5


def load(split):
    frame = pd.read_parquet(f"{SPLITS}/{split}.parquet")
    features = frame[PREDICTIVE_FEATURES].copy()
    for column in PREDICTIVE_FEATURES:
        if column not in CATEGORICAL:
            features[column] = pd.to_numeric(features[column], errors="coerce")
    return features, frame["is_withdrawn"].astype(int), frame[SENSITIVE].fillna("NaN").astype(str)


def evaluate(pipeline, features, labels):
    probabilities = pipeline.predict_proba(features)[:, 1]
    predicted = (probabilities >= ALERT_THRESHOLD).astype(int)
    return {"rows": int(len(labels)), "prevalence": float(labels.mean()), "roc_auc": float(roc_auc_score(labels, probabilities)),
            "pr_auc": float(average_precision_score(labels, probabilities)), "brier": float(brier_score_loss(labels, probabilities)),
            "precision_at_50": float(precision_score(labels, predicted, zero_division=0)),
            "recall_at_50": float(recall_score(labels, predicted, zero_division=0)), "f1_at_50": float(f1_score(labels, predicted, zero_division=0)),
            "share_alerted_at_50": float(predicted.mean())}


def committed_report():
    """The original team's metrics for the XGBoost baseline, if the report is present."""
    for path in glob.glob("reports/models/*.csv"):
        table = pd.read_csv(path)
        if "model" in table.columns and "validation_roc_auc" in table.columns:
            row = table[table["model"] == "xgb"]
            if len(row):
                return path, row.iloc[0].to_dict()
    return None, {}


def main():
    with open("configs/model_config.yaml") as f:
        config = yaml.safe_load(f)["models"]
    np.random.seed(config["random_state"])

    X_train, y_train, a_train = load("train")
    X_val, y_val, a_val = load("validation")

    pipeline = get_models(config)["xgb"]
    pipeline.fit(X_train, y_train)

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(MITIGATED_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(pipeline, f)

    mitigator = ThresholdOptimizer(estimator=pipeline, constraints="equalized_odds", predict_method="predict_proba", prefit=False)
    mitigator.fit(X_train, y_train, sensitive_features=a_train)
    joblib.dump(mitigator, MITIGATED_PATH)

    metrics = {"train": evaluate(pipeline, X_train, y_train), "validation": evaluate(pipeline, X_val, y_val)}
    for name, X, y, a in (("validation", X_val, y_val, a_val),):
        keep = a.isin(["M", "F"]).to_numpy()
        baseline = (pipeline.predict_proba(X[keep])[:, 1] >= ALERT_THRESHOLD).astype(int)
        adjusted = mitigator.predict(X[keep], sensitive_features=a[keep], random_state=FAIRNESS_SEED)
        metrics[name]["equalized_odds_gap_baseline"] = float(equalized_odds_difference(y[keep], baseline, sensitive_features=a[keep]))
        metrics[name]["equalized_odds_gap_mitigated"] = float(equalized_odds_difference(y[keep], adjusted, sensitive_features=a[keep]))

    path, report = committed_report()
    comparison = {}
    for key in ("train_roc_auc", "train_pr_auc", "validation_roc_auc", "validation_pr_auc"):
        split, metric = key.split("_", 1)
        if key in report:
            comparison[key] = {"retrained": round(metrics[split][metric], 4), "committed_report": round(float(report[key]), 4)}

    print(json.dumps({"metrics": metrics, "report_file": path, "comparison_with_committed_report": comparison}, indent=2))


if __name__ == "__main__":
    main()
