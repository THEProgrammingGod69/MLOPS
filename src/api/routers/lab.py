"""Alert desk, institution data adapter and decision lab (/api/v1)."""
import json
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from src.adapter import mapper
from src.adapter.vocabulary import TARGETS
from src.api import alert_sync, lab
from src.api.alert_desk import add_top_drivers, alert_desk, raise_alerts
from src.api.feature_catalog import feature_label
from src.api.inference import inference_service
from src.api.schemas import BatchStudent, PredictiveFeatures
from src.api.settings import settings
from src.api.telemetry import record_predictions
from src.models.train_baselines import PREDICTIVE_FEATURES
from src.monitoring import application_metrics as m

router = APIRouter(prefix="/api/v1", tags=["alerts, adapter, lab"])
MAX_UPLOAD_BYTES = 4 * 1024 * 1024


def origin_of(request: Request) -> str:
    return "simulator" if request.headers.get("x-traffic-origin", "").lower() == "simulator" else "user"


def _tier(probability: float) -> str:
    return inference_service.intervention_engine.generate_recommendation(probability)["risk_tier"]


def _require_model() -> None:
    if not inference_service.loaded:
        raise HTTPException(status_code=503, detail="Model is not loaded")


def _as_dicts(students: List[PredictiveFeatures]) -> List[Dict]:
    return [{k: getattr(s, k) for k in PREDICTIVE_FEATURES} for s in students]


# ------------------------------------------------------------------------------- alert desk
class AckRequest(BaseModel):
    assignee: Optional[str] = Field(None, max_length=80)
    note: Optional[str] = Field(None, max_length=400)


class RestoreRequest(BaseModel):
    cases: List[dict] = Field(default_factory=list, max_length=200)


class SyncRequest(RestoreRequest):
    acknowledged: List[dict] = Field(default_factory=list, max_length=200)


CASE_FIELDS = {"ref", "risk_probability", "risk_tier", "intervention_level"}


@router.get("/alerts")
def list_alerts(limit: int = 100):
    return alert_desk.snapshot(limit=min(limit, 200))


@router.post("/alerts/{case_id}/acknowledge")
def acknowledge_alert(case_id: str, body: AckRequest):
    return alert_desk.acknowledge(case_id, body.assignee, body.note) or alert_desk.acknowledge_unknown(case_id, body.assignee, body.note)


@router.post("/alerts/restore")
def restore_alerts(body: RestoreRequest):
    valid = [c for c in body.cases if CASE_FIELDS <= set(c)]
    return {"restored": alert_desk.restore(valid)}


@router.post("/alerts/sync", include_in_schema=False)
def sync_alerts(body: SyncRequest):
    """Instance-to-instance agreement on real users' cases (see src/api/alert_sync.py)."""
    alert_desk.merge({"cases": [c for c in body.cases if CASE_FIELDS <= set(c)], "acknowledged": [c for c in body.acknowledged if "ref" in c and "acknowledged_at" in c]})
    return alert_desk.sync_state()


@router.get("/touch", include_in_schema=False, status_code=204)
def touch():
    """nginx mirrors Grafana traffic here, so sync also runs while only Grafana is open."""
    alert_sync.touch()


# ------------------------------------------------------------------------------- adapter
async def _read_upload(file: UploadFile) -> pd.DataFrame:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than the 4 MB upload limit. Split it or drop unused columns.")
    try:
        frame = mapper.read_table(content, file.filename or "upload.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read this file: {exc}")
    if frame.empty or frame.shape[1] < 2:
        raise HTTPException(status_code=400, detail="The file needs a header row and at least two columns.")
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame.loc[:, ~frame.columns.duplicated()]
    return frame


@router.get("/adapter/targets")
def adapter_targets():
    return {"targets": [{"feature": f, "label": feature_label(f), "kind": s["kind"],
                         "transforms": mapper.TRANSFORMS.get(s["kind"], ["as_is"])} for f, s in TARGETS.items()]}


@router.post("/adapter/inspect")
async def adapter_inspect(file: UploadFile = File(...)):
    frame = await _read_upload(file)
    profiles = {c: mapper.profile_column(frame[c]) for c in frame.columns}
    proposal = mapper.match_columns(frame, profiles)
    return {"filename": file.filename, "rows": int(len(frame)), "columns": list(profiles.values()), "proposal": proposal,
            "targets": adapter_targets()["targets"], "preview": frame.head(5).astype(object).where(frame.head(5).notna(), None).to_dict(orient="records")}


@router.post("/adapter/score")
async def adapter_score(request: Request, file: UploadFile = File(...), mapping: str = Form(...), cohort: str = Form("uploaded cohort"),
                        as_of: Optional[str] = Form(None)):
    _require_model()
    frame = await _read_upload(file)
    try:
        plan = json.loads(mapping)
        plan["targets"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="The mapping is not valid JSON with a 'targets' object.")

    truncated = max(0, len(frame) - settings.max_batch_size)
    frame = frame.head(settings.max_batch_size).reset_index(drop=True)
    adapted = mapper.adapt(frame, plan, as_of=as_of)
    features = adapted["features"]
    genders = adapted["gender"]
    identifiers = adapted["identifiers"]
    references = [str(identifiers.iloc[i]) if identifiers is not None and pd.notna(identifiers.iloc[i]) else f"row-{i + 1}" for i in range(len(frame))]

    records = features.astype(object).where(features.notna(), None).to_dict(orient="records")
    students = []
    for i, record in enumerate(records):
        gender = genders.iloc[i] if genders is not None and pd.notna(genders.iloc[i]) else None
        students.append(BatchStudent(record_id=references[i][:128], gender=gender, **record))

    started = time.perf_counter()
    results = inference_service.score(students)
    raw = np.array([r["risk_probability"] for r in results])
    report = mapper.fit_report(adapted)
    validation = mapper.local_validation(raw, mapper.outcomes_from(frame, plan.get("roles", {}).get("outcome")))
    calibrated = validation.pop("calibrated")
    final = calibrated if calibrated is not None else raw
    for result, probability in zip(results, final):
        recommendation = inference_service.intervention_engine.generate_recommendation(float(probability))
        result.update(risk_probability=float(probability), priority_score=float(probability), risk_tier=recommendation["risk_tier"],
                      intervention_level=recommendation["intervention_level"], human_review_required=bool(recommendation["human_review_required"]),
                      recommended_actions=list(recommendation["recommended_actions"]))
    add_top_drivers(students, results)
    elapsed = time.perf_counter() - started
    record_predictions(results, source="batch")
    opened = raise_alerts(results, origin_of(request), references=references, cohort=cohort)
    m.ADAPTER_RUNS.labels(verdict=report["verdict"]).inc()
    m.ADAPTER_ROWS.inc(len(results))
    m.ADAPTER_FIT.set(report["score"])

    ranks = pd.Series(final).rank(pct=True).to_numpy()
    tiers = {t: 0 for t in ("LOW", "MODERATE", "HIGH", "CRITICAL")}
    rows = []
    for i, result in enumerate(results):
        tiers[result["risk_tier"]] += 1
        rows.append({"reference": references[i], "risk_probability": result["risk_probability"], "raw_probability": float(raw[i]),
                     "risk_tier": result["risk_tier"], "cohort_percentile": round(float(ranks[i]) * 100, 1),
                     "intervention_level": result["intervention_level"], "top_driver": result.get("top_driver"),
                     "features": _jsonable(records[i])})
    rows.sort(key=lambda r: -r["risk_probability"])
    return {"model_version": inference_service.model_version, "latency_ms": round(elapsed * 1000, 1), "cohort": cohort,
            "count": len(rows), "truncated_rows": truncated, "tier_counts": tiers, "alerts_opened": len(opened),
            "alert_threshold": alert_desk.threshold, "alerts": opened,
            "calibrated": calibrated is not None, "fit": report, "validation": validation, "rows": rows}


def _jsonable(record: Dict) -> Dict:
    return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in record.items()}


# ------------------------------------------------------------------------------- decision lab
class RescueRequest(BaseModel):
    student: PredictiveFeatures
    target: float = Field(alert_desk.threshold, gt=0, lt=1)


class CohortRequest(BaseModel):
    students: List[BatchStudent] = Field(..., min_length=1)


class TriageRequest(CohortRequest):
    advisor_hours: float = Field(10, gt=0, le=500)
    response_rate: float = Field(0.6, gt=0, le=1)
    min_risk: float = Field(0.3, ge=0, lt=1)


class StressRequest(CohortRequest):
    scenario: str = "lms_outage"
    engagement: float = Field(1.0, gt=0, le=3)
    score_shift: float = Field(0.0, ge=-50, le=50)
    delay_shift: float = Field(0.0, ge=-30, le=30)


def _references(students: List[BatchStudent]) -> List[str]:
    return [s.record_id or f"row-{i + 1}" for i, s in enumerate(students)]


def _check_size(students: list) -> None:
    if len(students) > settings.max_batch_size:
        raise HTTPException(status_code=413, detail=f"Cohort of {len(students)} exceeds the limit of {settings.max_batch_size}")


@router.post("/lab/rescue")
def rescue(body: RescueRequest):
    _require_model()
    return lab.rescue_plans(_as_dicts([body.student]), target=body.target)[0]


@router.get("/lab/scenarios")
def scenarios():
    return {"scenarios": [{"id": k, **v} for k, v in lab.SCENARIOS.items()]}


@router.post("/lab/triage")
def triage(body: TriageRequest):
    _require_model()
    _check_size(body.students)
    return lab.plan_triage(_as_dicts(body.students), _references(body.students), body.advisor_hours, body.response_rate,
                           body.min_risk, tier_of=_tier)


@router.post("/lab/stress")
def stress(body: StressRequest):
    _require_model()
    _check_size(body.students)
    if body.scenario not in lab.SCENARIOS and body.scenario != "custom":
        raise HTTPException(status_code=422, detail=f"Unknown scenario '{body.scenario}'")
    return lab.stress_test(_as_dicts(body.students), body.scenario, _references(body.students), body.engagement, body.score_shift, body.delay_shift)
