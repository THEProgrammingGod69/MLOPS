"""Runtime settings for the inference service.

Values come from ``configs/monitoring_config.yaml`` (live monitoring section) with
environment-variable overrides, so the same image runs locally, in Docker Compose
and in CI without code changes. All paths are relative to the project root, which
is the working directory for every entry point in this repository.
"""
import os
from dataclasses import dataclass, field
from typing import List

import yaml

SERVICE_NAME = "Student Dropout Early Warning API"
SERVICE_VERSION = "2.0.0"
MONITORING_CONFIG_PATH = "configs/monitoring_config.yaml"


def _env(name: str, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return type(default)(value) if not isinstance(default, str) else value


def _load_live_config(path: str = MONITORING_CONFIG_PATH) -> dict:
    try:
        with open(path, "r") as f:
            return (yaml.safe_load(f) or {}).get("monitoring", {}).get("live", {}) or {}
    except FileNotFoundError:
        return {}


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    model_path: str
    mitigation_model_path: str
    intervention_config_path: str
    monitoring_config_path: str
    reference_profile_path: str
    reports_dir: str
    ui_dist_dir: str
    drift_window_size: int
    drift_min_samples: int
    drift_min_samples_categorical: int
    recent_predictions_size: int
    max_batch_size: int
    grafana_url: str
    prometheus_url: str
    cors_origins: List[str] = field(default_factory=list)


def load_settings() -> Settings:
    live = _load_live_config()
    return Settings(
        model_path=_env("MODEL_PATH", "models/baseline/xgb_pipeline.pkl"),
        mitigation_model_path=_env(
            "MITIGATION_MODEL_PATH", "models/mitigated/xgb_threshold_optimizer_gender.pkl"
        ),
        intervention_config_path=_env("INTERVENTION_CONFIG_PATH", "configs/intervention_config.yaml"),
        monitoring_config_path=MONITORING_CONFIG_PATH,
        reference_profile_path=_env(
            "REFERENCE_PROFILE_PATH",
            live.get("reference_profile_path", "configs/drift_reference_profile.json"),
        ),
        reports_dir=_env("REPORTS_DIR", "reports"),
        ui_dist_dir=_env("UI_DIST_DIR", "frontend/dist"),
        drift_window_size=_env("DRIFT_WINDOW_SIZE", int(live.get("window_size", 2000))),
        drift_min_samples=_env("DRIFT_MIN_SAMPLES", int(live.get("min_samples", 500))),
        drift_min_samples_categorical=_env(
            "DRIFT_MIN_SAMPLES_CATEGORICAL", int(live.get("min_samples_categorical", 1500))
        ),
        recent_predictions_size=_env("RECENT_PREDICTIONS_SIZE", int(live.get("recent_predictions", 200))),
        max_batch_size=_env("MAX_BATCH_SIZE", int(live.get("max_batch_size", 2000))),
        grafana_url=_env("GRAFANA_URL", "http://localhost:3000"),
        prometheus_url=_env("PROMETHEUS_URL", "http://localhost:9090"),
        cors_origins=_split_csv(
            _env(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
            )
        ),
    )


settings = load_settings()
