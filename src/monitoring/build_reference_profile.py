"""Build the reference profile used for live drift monitoring.

The profile summarises the training reference split so the API can compute drift
without shipping any training rows inside the container:

* numeric features: decile bin edges, the reference share of each bin
  (computed on the data itself, so ties and discrete values are exact),
  the missing-value rate and the mean;
* categorical features: category frequencies.

Usage (from the project root)::

    python -m src.monitoring.build_reference_profile            # auto: parquet if present, else EDA fallback
    python -m src.monitoring.build_reference_profile --source parquet --input data/processed/splits/development_train.parquet
    python -m src.monitoring.build_reference_profile --source eda

The EDA fallback only has the min/25/50/75/95th percentile/max from
``reports/eda/numeric_summary.csv``. Assuming 25/25/25/20/5 % bin shares is only
safe when no single value carries much mass at a bin edge, so it keeps features
whose quantiles are strictly increasing *and* that have at least
``EDA_MIN_UNIQUE`` distinct values (``reports/eda/column_profile.csv``). It has no
categorical frequencies and is marked ``approximate`` in the output.
"""
import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from src.models.train_baselines import PREDICTIVE_FEATURES

CATEGORICAL_FEATURES = ["highest_education", "code_module", "code_presentation"]
NUMERIC_FEATURES = [f for f in PREDICTIVE_FEATURES if f not in CATEGORICAL_FEATURES]
DEFAULT_OUTPUT = "configs/drift_reference_profile.json"
EDA_SUMMARY = "reports/eda/numeric_summary.csv"
EDA_COLUMN_PROFILE = "reports/eda/column_profile.csv"
EDA_MIN_UNIQUE = 500


def _reference_path() -> str:
    with open("configs/monitoring_config.yaml", "r") as f:
        return yaml.safe_load(f)["monitoring"]["reference_data_path"]


def build_from_dataframe(df: pd.DataFrame, bins: int = 10, source: str = "development_train") -> dict:
    profile = {"version": 1, "source": source, "approximate": False,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "n_rows": int(len(df)), "numeric": {}, "categorical": {}}
    for feature in NUMERIC_FEATURES:
        if feature not in df.columns:
            continue
        values = pd.to_numeric(df[feature], errors="coerce").to_numpy(dtype=float)
        present = values[~np.isnan(values)]
        if len(present) == 0:
            continue
        quantiles = np.quantile(present, np.linspace(0, 1, bins + 1)[1:-1])
        edges = np.unique(quantiles)
        counts = np.bincount(np.searchsorted(edges, present, side="right"), minlength=len(edges) + 1)
        profile["numeric"][feature] = {
            "edges": [float(e) for e in edges],
            "proportions": [float(c) for c in counts / len(present)],
            "missing_rate": float(np.isnan(values).mean()),
            "mean": float(present.mean()),
            "min": float(present.min()),
            "max": float(present.max()),
        }
    for feature in CATEGORICAL_FEATURES:
        if feature not in df.columns:
            continue
        frequencies = df[feature].fillna("Missing").astype(str).value_counts(normalize=True)
        profile["categorical"][feature] = {"frequencies": {k: float(v) for k, v in frequencies.items()}}
    return profile


def build_from_eda_summary(path: str = EDA_SUMMARY, column_profile_path: str = EDA_COLUMN_PROFILE) -> dict:
    summary = pd.read_csv(path, index_col=0)
    unique_values = pd.read_csv(column_profile_path, index_col=0)["unique_values"]
    profile = {"version": 1, "source": "eda_numeric_summary", "approximate": True,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "n_rows": None, "numeric": {}, "categorical": {},
               "note": "Quartile-based approximation from reports/eda/numeric_summary.csv. "
                       "Run with --source parquet on the development_train split for exact deciles."}
    for feature in NUMERIC_FEATURES:
        if feature not in summary.index:
            continue
        row = summary.loc[feature]
        points = [float(row[q]) for q in ("min", "25%", "50%", "75%", "95%", "max")]
        if any(b <= a for a, b in zip(points, points[1:])):
            continue  # tied quantiles: bin shares unknowable without raw data
        if int(unique_values.get(feature, 0)) < EDA_MIN_UNIQUE:
            continue  # coarse values put unknown mass on bin edges
        edges = points[1:-1]
        total = float(row["count"]) + float(row["missing"])
        profile["numeric"][feature] = {
            "edges": edges,
            "proportions": [0.25, 0.25, 0.25, 0.20, 0.05],
            "missing_rate": float(row["missing"]) / total if total else 0.0,
            "mean": float(row["mean"]),
            "min": points[0],
            "max": points[-1],
        }
    return profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", choices=["auto", "parquet", "eda"], default="auto")
    parser.add_argument("--input", default=None, help="Reference parquet (defaults to monitoring_config reference_data_path)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args(argv)

    parquet_path = args.input or _reference_path()
    source = args.source
    if source == "auto":
        source = "parquet" if os.path.exists(parquet_path) else "eda"

    if source == "parquet":
        profile = build_from_dataframe(pd.read_parquet(parquet_path), bins=args.bins,
                                       source=os.path.splitext(os.path.basename(parquet_path))[0])
    else:
        profile = build_from_eda_summary()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(profile, f, indent=2)
    print(f"Reference profile ({profile['source']}, approximate={profile['approximate']}) -> {args.output}: "
          f"{len(profile['numeric'])} numeric, {len(profile['categorical'])} categorical features")
    return profile


if __name__ == "__main__":
    main()
