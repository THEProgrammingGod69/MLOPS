"""Alert desk: every student scored at or above the alert threshold opens a case.

The threshold defaults to 50 % (``ALERT_THRESHOLD``), the same cut that starts the
CRITICAL tier. Open cases are exported as one bounded gauge,
``student_dropout_alert_open``, so Prometheus can fire ``StudentDropoutRiskAbove50``
per student and Grafana can list them.

Two rings keep the label set bounded. Cases raised by real users are never pushed
out by the traffic simulator, and the simulator can only ever occupy a few slots.
The server stores and exports only a salted pseudonym (``S-3F9A1C``), never the id the
institution supplied. The real id is returned once, to the person who submitted it, and stays
in their browser. A case's id is its pseudonym, so it means the same thing on every instance.
"""
import hashlib
import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Dict, List, Optional

from src.api.feature_catalog import feature_label
from src.api.inference import inference_service
from src.monitoring import application_metrics as m

MAX_EXPLAINED_ALERTS = 300
ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "0.5"))
_SALT = os.environ.get("ALERT_PSEUDONYM_SALT", "early-warning-demo")
USER_CAPACITY = 200
SIMULATOR_CAPACITY = 12
ORIGINS = ("user", "simulator")


def pseudonym(reference: str) -> str:
    digest = hashlib.sha256(f"{_SALT}:{reference}".encode("utf-8")).hexdigest()
    return f"S-{digest[:6].upper()}"


class AlertDesk:
    def __init__(self, threshold: float = ALERT_THRESHOLD):
        self.threshold = threshold
        self._lock = threading.Lock()
        self._open: Dict[str, "OrderedDict[str, dict]"] = {o: OrderedDict() for o in ORIGINS}
        self._acknowledged: "OrderedDict[str, dict]" = OrderedDict()
        for origin in ORIGINS:
            m.ALERTS_RAISED.labels(origin=origin)
            m.ALERTS_ACKNOWLEDGED.labels(origin=origin)
            m.ALERTS_OPEN.labels(origin=origin).set(0)

    # -- metric plumbing --------------------------------------------------------------
    @staticmethod
    def _labels(case: dict) -> dict:
        return {"student": case["ref"], "tier": case["risk_tier"], "driver": case["top_driver"] or "unknown",
                "cohort": case["cohort"], "origin": case["origin"]}

    def _export(self, case: dict) -> None:
        m.ALERT_OPEN.labels(**self._labels(case)).set(case["risk_probability"])

    def _retire(self, case: dict) -> None:
        try:
            m.ALERT_OPEN.remove(*[self._labels(case)[k] for k in m.ALERT_OPEN._labelnames])
        except KeyError:
            pass

    def _refresh_gauges(self) -> None:
        for origin in ORIGINS:
            m.ALERTS_OPEN.labels(origin=origin).set(len(self._open[origin]))

    # -- case lifecycle ---------------------------------------------------------------
    def raise_case(self, result: dict, origin: str, reference: Optional[str] = None,
                   cohort: Optional[str] = None, raised_at: Optional[float] = None,
                   count_metric: bool = True, ref: Optional[str] = None, updated_at: Optional[float] = None) -> Optional[dict]:
        probability = float(result["risk_probability"])
        if probability < self.threshold:
            return None
        origin = origin if origin in ORIGINS else "user"
        ref = ref or pseudonym(reference or result.get("prediction_id") or uuid.uuid4().hex)
        now = time.time()
        with self._lock:
            ring = self._open[origin]
            existing = ring.pop(ref, None)
            if existing is not None:
                self._retire(existing)
            self._acknowledged.pop(ref, None)  # scored again after being closed: it is a live case again
            case = {
                "id": ref,
                "ref": ref,
                "risk_probability": round(probability, 4),
                "risk_tier": result["risk_tier"],
                "intervention_level": result["intervention_level"],
                "top_driver": result.get("top_driver"),
                "cohort": (cohort or "ad-hoc")[:40],
                "origin": origin,
                "raised_at": existing["raised_at"] if existing else (now if raised_at is None else raised_at),
                "updated_at": now if updated_at is None else updated_at,
                "status": "open",
                "assignee": None,
                "note": None,
            }
            ring[ref] = case
            self._export(case)
            capacity = USER_CAPACITY if origin == "user" else SIMULATOR_CAPACITY
            while len(ring) > capacity:
                _, evicted = ring.popitem(last=False)
                self._retire(evicted)
            self._refresh_gauges()
        if count_metric and existing is None:
            m.ALERTS_RAISED.labels(origin=origin).inc()
        return case

    def _close(self, ring: "OrderedDict[str, dict]", case: dict, assignee, note, at: float) -> dict:
        del ring[case["ref"]]
        self._retire(case)
        case.update(status="acknowledged", assignee=assignee or None, note=note or None, acknowledged_at=at)
        self._acknowledged[case["ref"]] = case
        while len(self._acknowledged) > USER_CAPACITY:
            self._acknowledged.popitem(last=False)
        self._refresh_gauges()
        return case

    def acknowledge(self, case_id: str, assignee: Optional[str] = None, note: Optional[str] = None) -> Optional[dict]:
        with self._lock:
            for origin, ring in self._open.items():
                case = ring.get(case_id)
                if case is None:
                    continue
                now = time.time()
                m.ALERTS_ACKNOWLEDGED.labels(origin=origin).inc()
                m.ALERT_ACK_SECONDS.observe(max(0.0, now - case["raised_at"]))
                return self._close(ring, case, assignee, note, now)
        return None

    def acknowledge_unknown(self, case_id: str, assignee: Optional[str] = None, note: Optional[str] = None) -> dict:
        """Acknowledge a case this instance has not heard of yet; sync carries it to the rest."""
        with self._lock:
            known = self._acknowledged.get(case_id)
            if known is not None:
                return known
            now = time.time()
            closed = {"id": case_id, "ref": case_id, "status": "acknowledged", "assignee": assignee or None, "note": note or None,
                      "origin": "user", "acknowledged_at": now, "updated_at": now, "raised_at": now, "risk_probability": 0.0,
                      "risk_tier": "CRITICAL", "intervention_level": "", "top_driver": None, "cohort": "ad-hoc"}
            self._acknowledged[case_id] = closed
            return closed

    def restore(self, cases: List[dict]) -> int:
        """Re-open cases a browser kept across a scale-to-zero restart (the server starts empty)."""
        restored = 0
        for item in cases[:USER_CAPACITY]:
            if item["ref"] in self._open["user"] or self._closed_after(item):
                continue
            if self._merge_case(item) is not None:
                restored += 1
        return restored

    # -- agreement between instances ----------------------------------------------------
    def _closed_after(self, item: dict) -> bool:
        closed = self._acknowledged.get(item["ref"])
        return closed is not None and closed.get("acknowledged_at", 0) >= item.get("updated_at", 0)

    def _merge_case(self, item: dict) -> Optional[dict]:
        result = {"risk_probability": item["risk_probability"], "risk_tier": item["risk_tier"],
                  "intervention_level": item["intervention_level"], "top_driver": item.get("top_driver")}
        return self.raise_case(result, "user", ref=item["ref"], cohort=item.get("cohort"), raised_at=item.get("raised_at"),
                               updated_at=item.get("updated_at"), count_metric=False)

    def sync_state(self) -> dict:
        with self._lock:
            return {"cases": list(self._open["user"].values()), "acknowledged": list(self._acknowledged.values())}

    def merge(self, state: dict) -> None:
        """Adopt what a peer knows; the most recent change to a case wins."""
        for closed in state.get("acknowledged", [])[:USER_CAPACITY]:
            with self._lock:
                ref = closed["ref"]
                known = self._acknowledged.get(ref)
                if known is not None and known.get("acknowledged_at", 0) >= closed.get("acknowledged_at", 0):
                    continue
                case = self._open["user"].get(ref)
                if case is None:
                    self._acknowledged[ref] = closed
                elif case["updated_at"] <= closed.get("acknowledged_at", 0):
                    self._close(self._open["user"], case, closed.get("assignee"), closed.get("note"), closed["acknowledged_at"])
        for item in state.get("cases", [])[:USER_CAPACITY]:
            existing = self._open["user"].get(item["ref"])
            if (existing is not None and existing["updated_at"] >= item.get("updated_at", 0)) or self._closed_after(item):
                continue
            self._merge_case(item)

    # -- reads ------------------------------------------------------------------------
    def snapshot(self, limit: int = 100) -> dict:
        with self._lock:
            open_cases = [c for ring in self._open.values() for c in ring.values()]
            acknowledged = list(self._acknowledged.values())
        open_cases.sort(key=lambda c: (c["origin"] != "user", -c["risk_probability"]))
        acknowledged.sort(key=lambda c: -c.get("acknowledged_at", 0))
        return {
            "threshold": self.threshold,
            "open_count": len(open_cases),
            "open_user_count": sum(c["origin"] == "user" for c in open_cases),
            "open": open_cases[:limit],
            "acknowledged": acknowledged[:limit],
        }


alert_desk = AlertDesk()


def add_top_drivers(students, results: List[dict]) -> None:
    """Explain the highest-risk rows that lack a driver, so every alert can say why (bounded cost)."""
    if inference_service.explainer is None:
        return
    flagged = [i for i, r in enumerate(results) if r["risk_probability"] >= alert_desk.threshold and not r.get("top_driver")]
    flagged = sorted(flagged, key=lambda i: -results[i]["risk_probability"])[:MAX_EXPLAINED_ALERTS]
    if not flagged:
        return
    try:
        contributions, _ = inference_service.explainer.explain(inference_service.to_frame([students[i] for i in flagged]))
    except Exception:  # an alert without a named driver is still an alert
        return
    for position, row in zip(flagged, contributions):
        feature, value = max(inference_service.explainer.aggregate(row).items(), key=lambda kv: kv[1])
        results[position]["top_driver"] = feature_label(feature) if value > 0 else None


def raise_alerts(results: List[dict], origin: str, references: Optional[List[Optional[str]]] = None,
                 cohort: Optional[str] = None, count_metric: bool = True) -> List[dict]:
    """Open a case for every result at or above the threshold.

    Returns copies carrying the caller's own reference, for the response to that caller only.
    """
    opened = []
    for index, result in enumerate(results):
        reference = references[index] if references else None
        case = alert_desk.raise_case(result, origin, reference=reference, cohort=cohort, count_metric=count_metric)
        if case is not None:
            opened.append({**case, "reference": reference})
    return opened
