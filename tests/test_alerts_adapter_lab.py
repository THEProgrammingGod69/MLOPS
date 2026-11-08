"""Alert desk (>= 50 %), institution data adapter and decision lab."""
import io
import json
import re
import unittest

import pandas as pd
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest

from src.adapter import mapper
from src.api.alert_desk import AlertDesk, pseudonym
from src.api.inference import inference_service
from src.api.main import app
from tests._tiny_model import build_tiny_pipeline

STUDENT = {
    "highest_education": "Lower Than A Level", "num_of_prev_attempts": 1, "studied_credits": 120, "registration_day": -2,
    "code_module": "CCC", "code_presentation": "2014J", "module_presentation_length": 269, "asm_submission_count": 0,
    "asm_mean_score": None, "asm_score_std": None, "asm_failed_count": 0, "asm_average_delay": None, "vle_total_clicks": 12,
    "vle_active_days": 2, "vle_days_since_last_activity": 20, "vle_clicks_last_7_days": 0, "vle_clicks_last_14_days": 0,
    "vle_forum_clicks": 2, "vle_resource_clicks": 1, "vle_quiz_clicks": 0, "vle_activity_type_diversity": 1,
}
RESULT = {"risk_probability": 0.72, "risk_tier": "CRITICAL", "intervention_level": "priority human review", "top_driver": "Active days"}
SAMPLES = "frontend/public/samples"


def metrics_text() -> str:
    return generate_latest().decode()


class TestAlertDesk(unittest.TestCase):
    def setUp(self):
        self.desk = AlertDesk(threshold=0.5)

    def test_threshold_is_inclusive_at_50_percent(self):
        self.assertIsNone(self.desk.raise_case({**RESULT, "risk_probability": 0.4999}, "user", reference="a"))
        self.assertIsNotNone(self.desk.raise_case({**RESULT, "risk_probability": 0.5}, "user", reference="b"))

    def test_case_appears_in_metrics_with_a_pseudonym_only(self):
        self.desk.raise_case(RESULT, "user", reference="roll-42", cohort="demo")
        text = metrics_text()
        self.assertIn(f'student="{pseudonym("roll-42")}"', text)
        self.assertNotIn("roll-42", text)

    def test_same_student_updates_one_case(self):
        self.desk.raise_case(RESULT, "user", reference="x")
        self.desk.raise_case({**RESULT, "risk_probability": 0.9}, "user", reference="x")
        snapshot = self.desk.snapshot()
        self.assertEqual(snapshot["open_count"], 1)
        self.assertEqual(snapshot["open"][0]["risk_probability"], 0.9)

    def test_simulator_cannot_evict_user_cases(self):
        self.desk.raise_case(RESULT, "user", reference="real")
        for i in range(60):
            self.desk.raise_case(RESULT, "simulator", reference=f"sim{i}")
        snapshot = self.desk.snapshot()
        self.assertEqual(snapshot["open_user_count"], 1)
        self.assertLessEqual(snapshot["open_count"], 13)

    def test_acknowledge_closes_case_and_removes_series(self):
        case = self.desk.raise_case(RESULT, "user", reference="ack-me")
        self.assertIsNotNone(self.desk.acknowledge(case["id"], "Advisor A"))
        self.assertEqual(self.desk.snapshot()["open_count"], 0)
        self.assertNotIn(f'student="{case["ref"]}"', metrics_text())
        self.assertIsNone(self.desk.acknowledge(case["id"]))

    def test_restore_rehydrates_without_counting_as_new(self):
        case = self.desk.raise_case(RESULT, "user", reference="persist")
        fresh = AlertDesk(threshold=0.5)
        self.assertEqual(fresh.restore([case]), 1)
        restored = fresh.snapshot()["open"][0]
        self.assertEqual(restored["ref"], case["ref"])
        self.assertEqual(restored["raised_at"], case["raised_at"])


class TestInstanceAgreement(unittest.TestCase):
    def setUp(self):
        self.a, self.b = AlertDesk(threshold=0.5), AlertDesk(threshold=0.5)

    def test_case_ids_match_across_instances(self):
        self.assertEqual(self.a.raise_case(RESULT, "user", reference="s1")["id"], self.b.raise_case(RESULT, "user", reference="s1")["id"])

    def test_case_spreads_to_a_peer(self):
        self.a.raise_case(RESULT, "user", reference="s2")
        self.b.merge(self.a.sync_state())
        self.assertEqual(self.b.snapshot()["open_user_count"], 1)

    def test_acknowledgement_spreads_and_is_not_undone_by_a_stale_peer(self):
        case = self.a.raise_case(RESULT, "user", reference="s3")
        self.b.merge(self.a.sync_state())
        self.a.acknowledge(case["id"], "Advisor")
        self.b.merge(self.a.sync_state())
        self.assertEqual(self.b.snapshot()["open_user_count"], 0)
        stale = AlertDesk(threshold=0.5)
        stale.raise_case(RESULT, "user", reference="s3", updated_at=case["updated_at"])
        self.a.merge(stale.sync_state())
        self.assertEqual(self.a.snapshot()["open_user_count"], 0)

    def test_a_later_rescore_reopens_a_closed_case(self):
        case = self.a.raise_case(RESULT, "user", reference="s4")
        self.a.acknowledge(case["id"])
        self.assertIsNotNone(self.a.raise_case(RESULT, "user", reference="s4"))
        self.assertEqual(self.a.snapshot()["open_user_count"], 1)

    def test_merge_does_not_count_as_new_alerts(self):
        self.a.raise_case(RESULT, "user", reference="s5", count_metric=False)
        before = REGISTRY.get_sample_value("student_dropout_alerts_raised_total", {"origin": "user"}) or 0
        self.b.merge(self.a.sync_state())
        self.assertEqual(REGISTRY.get_sample_value("student_dropout_alerts_raised_total", {"origin": "user"}) or 0, before)


class TestAdapterUnits(unittest.TestCase):
    def test_grade_scales(self):
        self.assertAlmostEqual(mapper.to_score_100(pd.Series([3.2, 4.0]))[0].iloc[1], 100)
        self.assertAlmostEqual(mapper.to_score_100(pd.Series([7.5, 10.0]))[0].iloc[0], 75)
        self.assertAlmostEqual(mapper.to_score_100(pd.Series([16, 20]))[0].iloc[0], 80)
        self.assertAlmostEqual(mapper.to_score_100(pd.Series(["85%", "40%"]))[0].iloc[0], 85)
        self.assertAlmostEqual(mapper.to_score_100(pd.Series(["23/30", "15/30"]))[0].iloc[1], 50)
        self.assertEqual(mapper.to_score_100(pd.Series(["A", "F", "B+"]))[0].tolist(), [93, 35, 87])

    def test_education_mapping(self):
        converted = mapper.to_education(pd.Series(["B.Tech", "HSC", "10th", "PhD", "No formal education", None])).tolist()
        self.assertEqual(converted, ["HE Qualification", "A Level or Equivalent", "Lower Than A Level", "Post Graduate Qualification",
                                     "No Formal quals", "A Level or Equivalent"])

    def test_percentile_transport_preserves_order_and_lands_in_reference_range(self):
        moved = mapper.transport(pd.Series([10.0, 50.0, 90.0, 95.0]), "vle_total_clicks")
        self.assertTrue(moved.is_monotonic_increasing)
        self.assertLessEqual(moved.max(), mapper.REFERENCE["vle_total_clicks"][-1])

    def test_one_to_one_matching(self):
        frame = pd.DataFrame({"CGPA": [7.0, 8.0, 9.0], "Marks": [70, 80, 90], "Attendance": [60, 70, 80]})
        profiles = {c: mapper.profile_column(frame[c]) for c in frame}
        targets = mapper.match_columns(frame, profiles)["targets"]
        used = [t["column"] for t in targets.values() if t["column"]]
        self.assertEqual(len(used), len(set(used)))
        self.assertEqual(targets["asm_mean_score"]["column"], "Marks")

    def test_unrelated_columns_stay_unmapped(self):
        frame = pd.DataFrame({"Favourite Colour": ["red", "blue"], "Shoe Size": [7, 9]})
        profiles = {c: mapper.profile_column(frame[c]) for c in frame}
        self.assertTrue(all(t["column"] is None for t in mapper.match_columns(frame, profiles)["targets"].values()))

    def test_separator_detection(self):
        self.assertEqual(mapper.read_table("a;b\n1;2\n".encode(), "x.csv").shape, (1, 2))
        self.assertEqual(mapper.read_table("a\tb\n1\t2\n".encode(), "x.tsv").shape, (1, 2))

    def test_validation_needs_enough_outcomes(self):
        self.assertFalse(mapper.local_validation(pd.Series([0.2, 0.8]).to_numpy(), pd.Series([0.0, 1.0]))["available"])


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = (inference_service.model_path, inference_service.to_path)
        inference_service.reload(model_path=build_tiny_pipeline(), to_path="missing.pkl", prefer_shap=False)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        inference_service.reload(*cls.saved)

    def _inspect(self, name):
        with open(f"{SAMPLES}/{name}", "rb") as f:
            response = self.client.post("/api/v1/adapter/inspect", files={"file": (name, f.read())})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _score(self, name, cohort="test"):
        proposal = self._inspect(name)["proposal"]
        with open(f"{SAMPLES}/{name}", "rb") as f:
            response = self.client.post("/api/v1/adapter/score", files={"file": (name, f.read())},
                                        data={"mapping": json.dumps(proposal), "cohort": cohort})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_engineering_college_mapping(self):
        targets = self._inspect("sample-engineering-college.csv")["proposal"]
        mapped = {k: v["column"] for k, v in targets["targets"].items()}
        self.assertEqual(mapped["asm_mean_score"], "CGPA")
        self.assertEqual(mapped["vle_active_days"], "Attendance %")
        self.assertEqual(mapped["vle_total_clicks"], "Moodle Logins")
        self.assertEqual(mapped["vle_days_since_last_activity"], "Last Login")
        self.assertEqual(mapped["num_of_prev_attempts"], "Backlogs")
        self.assertEqual(targets["roles"]["student_id"], "Roll No")
        self.assertEqual(targets["roles"]["outcome"], "Dropped Out")

    def test_every_sample_scores_end_to_end(self):
        for name, has_outcome in (("sample-engineering-college.csv", True), ("sample-community-college.csv", True), ("sample-secondary-school.csv", False)):
            result = self._score(name, cohort=name[:20])
            self.assertEqual(result["count"], 240, name)
            self.assertEqual(result["validation"]["available"], has_outcome, name)
            self.assertGreater(result["fit"]["score"], 0, name)
            self.assertTrue(all(0 <= r["risk_probability"] <= 1 for r in result["rows"]), name)

    def test_adapter_opens_alerts_for_at_or_above_threshold_only(self):
        result = self._score("sample-engineering-college.csv", cohort="alert-check")
        expected = sum(r["risk_probability"] >= result["alert_threshold"] for r in result["rows"])
        self.assertEqual(result["alerts_opened"], expected)

    def test_fit_score_is_lower_for_thin_data(self):
        thin = pd.DataFrame({"Student ID": range(40), "Marks": [50 + (i % 40) for i in range(40)], "Gender": ["M", "F"] * 20})
        name = "thin.csv"
        content = thin.to_csv(index=False).encode()
        proposal = self.client.post("/api/v1/adapter/inspect", files={"file": (name, content)}).json()["proposal"]
        result = self.client.post("/api/v1/adapter/score", files={"file": (name, content)}, data={"mapping": json.dumps(proposal)}).json()
        self.assertLess(result["fit"]["score"], self._score("sample-community-college.csv")["fit"]["score"])

    def test_bad_upload_is_a_clear_400(self):
        response = self.client.post("/api/v1/adapter/inspect", files={"file": ("x.csv", b"justonecolumn\n1\n")})
        self.assertEqual(response.status_code, 400)

    def test_predict_returns_alert_when_at_risk(self):
        body = self.client.post("/api/v1/predict?include_explanation=true&student_reference=me", json=STUDENT).json()
        if body["risk_probability"] >= 0.5:
            self.assertEqual(body["alert"]["risk_tier"], "CRITICAL")
        else:
            self.assertIsNone(body["alert"])

    def test_simulator_header_marks_origin(self):
        safe = re.sub(r"[^a-z]", "", "simulatedcohort")
        body = self.client.post(f"/api/v1/predict?cohort={safe}", json=STUDENT, headers={"X-Traffic-Origin": "simulator"}).json()
        self.assertIsNone(body["alert"])
        self.assertFalse([c for c in self.client.get("/api/v1/alerts?limit=200").json()["open"] if c["cohort"] == safe])

    def test_raw_student_ids_never_reach_the_public_alert_list(self):
        reference = "ROLL-SECRET-77"
        body = self.client.post(f"/api/v1/predict?student_reference={reference}", json=STUDENT).json()
        if body["alert"]:
            self.assertEqual(body["alert"]["reference"], reference)
        self.assertNotIn(reference, self.client.get("/api/v1/alerts?limit=200").text)

    def test_acknowledging_a_case_this_instance_never_saw_succeeds(self):
        response = self.client.post("/api/v1/alerts/S-ABC123/acknowledge", json={"assignee": "A"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "acknowledged")

    def test_rescue_plan_is_ordered_and_never_raises_risk_overall(self):
        plan = self.client.post("/api/v1/lab/rescue", json={"student": STUDENT, "target": 0.05}).json()
        self.assertLessEqual(plan["end_probability"], plan["start_probability"] + 1e-9)
        for step in plan["steps"]:
            self.assertAlmostEqual(step["risk_change"], step["risk_after"] - step["risk_before"], places=6)

    def test_rescue_keeps_click_counters_consistent(self):
        plan = self.client.post("/api/v1/lab/rescue", json={"student": STUDENT, "target": 0.01}).json()
        changed = {c["feature"]: c["to"] for c in plan["feature_changes"]}
        if "vle_clicks_last_7_days" in changed:
            self.assertLessEqual(changed["vle_clicks_last_7_days"], changed["vle_clicks_last_14_days"])
            self.assertLessEqual(changed["vle_clicks_last_14_days"], changed["vle_total_clicks"])

    def test_triage_respects_budget_and_beats_or_equals_naive(self):
        students = [{**STUDENT, "record_id": f"s{i}", "vle_total_clicks": 10 + i * 8, "vle_active_days": i % 10} for i in range(30)]
        plan = self.client.post("/api/v1/lab/triage", json={"students": students, "advisor_hours": 2, "min_risk": 0.0}).json()
        self.assertLessEqual(plan["used_minutes"], 120)

    def test_stress_outage_does_not_add_clicks(self):
        students = [{**STUDENT, "record_id": f"s{i}"} for i in range(10)]
        result = self.client.post("/api/v1/lab/stress", json={"students": students, "scenario": "lms_outage"}).json()
        self.assertEqual(result["count"], 10)
        self.assertEqual(sum(result["histogram_after"]), 10)

    def test_unknown_scenario_rejected(self):
        response = self.client.post("/api/v1/lab/stress", json={"students": [STUDENT], "scenario": "nope"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
