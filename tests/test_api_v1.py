import random
import sys
import unittest

import numpy as np
from fastapi.testclient import TestClient

from src.api.explain import NATIVE_BACKEND, ExplanationEngine
from src.api.feature_catalog import (COURSE_CATALOG, FEATURE_CATALOG, SAMPLE_PROFILES, base_feature,
                                     transformed_label)
from src.api.inference import InferenceService, inference_service
from src.api.main import app
from src.api.schemas import PredictiveFeatures
from src.api.telemetry import publish_service_state
from src.models.train_baselines import PREDICTIVE_FEATURES
from tests._tiny_model import build_tiny_pipeline, synthetic_frame

client = TestClient(app)
SILENT = next(p for p in SAMPLE_PROFILES if p["id"] == "silent")["features"]


def setUpModule():
    # The real artifacts are DVC/gitignored; fall back to a tiny model so the API contract
    # is still exercised in CI. Locally, with the real model present, nothing is replaced.
    if not inference_service.is_healthy():
        inference_service.reload(model_path=build_tiny_pipeline())
        publish_service_state()


class TestFeatureCatalog(unittest.TestCase):
    def test_catalog_matches_training_features(self):
        self.assertEqual([f["name"] for f in FEATURE_CATALOG], PREDICTIVE_FEATURES)

    def test_samples_validate_against_schema(self):
        for sample in SAMPLE_PROFILES:
            PredictiveFeatures(**sample["features"])
            module, presentation = sample["features"]["code_module"], sample["features"]["code_presentation"]
            self.assertEqual(COURSE_CATALOG[module][presentation], sample["features"]["module_presentation_length"])

    def test_transformed_names_map_back(self):
        self.assertEqual(base_feature("num__asm_mean_score"), "asm_mean_score")
        self.assertEqual(base_feature("num__missingindicator_asm_mean_score"), "asm_mean_score")
        self.assertEqual(base_feature("cat__highest_education_A Level or Equivalent"), "highest_education")
        self.assertEqual(base_feature("cat__code_module_AAA"), "code_module")
        self.assertEqual(transformed_label("cat__code_module_AAA"), "Module = AAA")
        self.assertEqual(transformed_label("missingindicator_asm_mean_score"), "Mean assessment score is missing")


class TestExplanationEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_tiny_pipeline()
        cls.service = InferenceService(model_path=cls.path, to_path="does/not/exist.pkl", prefer_shap=False)

    def test_native_shap_is_additive(self):
        X = synthetic_frame(50, seed=9)
        contributions, base = self.service.explainer.explain(X)
        probabilities = self.service.pipeline.predict_proba(X)[:, 1]
        reconstructed = 1.0 / (1.0 + np.exp(-(contributions.sum(axis=1) + base)))
        np.testing.assert_allclose(reconstructed, probabilities, atol=1e-5)

    def test_aggregation_preserves_total(self):
        X = synthetic_frame(5, seed=2)
        contributions, _ = self.service.explainer.explain(X)
        aggregated = self.service.explainer.aggregate(contributions[0])
        self.assertEqual(set(aggregated), set(PREDICTIVE_FEATURES))
        self.assertAlmostEqual(sum(aggregated.values()), float(contributions[0].sum()), places=4)

    def test_optional_components_fail_independently(self):
        self.assertTrue(self.service.is_healthy())
        self.assertFalse(self.service.components["fairness_mitigator"]["loaded"])
        self.assertEqual(self.service.explainer.backend, NATIVE_BACKEND)

    def test_missing_model_is_reported_not_raised(self):
        broken = InferenceService(model_path="does/not/exist.pkl", to_path="nope.pkl")
        self.assertFalse(broken.is_healthy())
        self.assertFalse(broken.components["model"]["loaded"])


class TestV1Endpoints(unittest.TestCase):
    def test_health_and_meta(self):
        body = client.get("/api/v1/health").json()
        self.assertEqual(body["status"], "healthy")
        self.assertIn("explainer", body["components"])
        self.assertIn("grafana", client.get("/api/v1/meta").json()["links"])

    def test_model_card(self):
        body = client.get("/api/v1/model").json()
        self.assertTrue(body["loaded"])
        self.assertEqual(len(body["version"]), 12)
        self.assertIn("critical", body["risk_tiers"])
        self.assertIn("roc_auc", body["offline_metrics"]["test"])

    def test_schema(self):
        body = client.get("/api/v1/schema").json()
        self.assertEqual(len(body["features"]), 21)
        self.assertEqual(len(body["samples"]), 4)

    def test_predict_with_explanation(self):
        body = client.post("/api/v1/predict", json=dict(SILENT, gender="F")).json()
        self.assertIn(body["risk_tier"], ("LOW", "MODERATE", "HIGH", "CRITICAL"))
        self.assertEqual(set(body["missing_features"]), {"asm_mean_score", "asm_score_std", "asm_average_delay"})
        contributions = body["explanation"]["contributions"]
        self.assertEqual(len(contributions), 21)
        magnitudes = [abs(c["contribution"]) for c in contributions]
        self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))
        total = body["explanation"]["base_value"] + sum(c["contribution"] for c in contributions)
        self.assertAlmostEqual(1.0 / (1.0 + np.exp(-total)), body["risk_probability"], places=4)

    def test_predict_without_explanation(self):
        body = client.post("/api/v1/predict?include_explanation=false", json=SILENT).json()
        self.assertIsNone(body["explanation"])
        self.assertEqual(body["risk_probability"], body["priority_score"])

    def test_null_only_allowed_for_genuinely_missing_features(self):
        self.assertEqual(client.post("/api/v1/predict", json=dict(SILENT, vle_total_clicks=None)).status_code, 422)
        payload = {k: v for k, v in SILENT.items() if k != "asm_mean_score"}
        self.assertEqual(client.post("/api/v1/predict", json=payload).status_code, 422)  # still required

    def test_batch(self):
        students = [dict(s["features"], record_id=s["id"]) for s in SAMPLE_PROFILES]
        response = client.post("/api/v1/predict/batch", json={"students": students, "include_explanation": True})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["summary"]["count"], 4)
        self.assertEqual(sum(body["summary"]["tier_counts"].values()), 4)
        self.assertEqual([r["record_id"] for r in body["results"]], [s["id"] for s in SAMPLE_PROFILES])
        single = client.post("/api/v1/predict?include_explanation=false", json=SAMPLE_PROFILES[0]["features"]).json()
        self.assertAlmostEqual(body["results"][0]["risk_probability"], single["risk_probability"], places=6)

    def test_batch_limits(self):
        self.assertEqual(client.post("/api/v1/predict/batch", json={"students": []}).status_code, 422)
        too_many = {"students": [SILENT] * 2001}
        self.assertEqual(client.post("/api/v1/predict/batch", json=too_many).status_code, 413)

    def test_insights_endpoints(self):
        for name in ("models", "explainability", "fairness", "interventions", "pipeline"):
            response = client.get(f"/api/v1/insights/{name}")
            self.assertEqual(response.status_code, 200, name)
        shap = client.get("/api/v1/insights/explainability").json()["shap"]
        self.assertTrue(all("label" in row for row in shap))

    def test_monitoring_endpoints_and_metrics(self):
        client.post("/api/v1/predict", json=SILENT)
        summary = client.get("/api/v1/monitoring/summary").json()
        self.assertGreaterEqual(summary["totals"]["predictions"], 1)
        drift = client.get("/api/v1/monitoring/drift").json()
        self.assertIn("features", drift)
        recent = client.get("/api/v1/monitoring/recent?limit=1").json()["items"]
        self.assertEqual(len(recent), 1)
        self.assertNotIn("inputs", recent[0])  # raw inputs never leave the process
        text = client.get("/metrics").text
        for name in ("student_dropout_predictions_total", "student_dropout_risk_probability_bucket",
                     "student_dropout_http_requests_total", "student_dropout_component_up",
                     "student_dropout_offline_model_metric", "student_dropout_window_predictions"):
            self.assertIn(name, text)
        self.assertNotIn('route="/metrics"', text)


class TestTrafficSimulator(unittest.TestCase):
    def test_generated_students_are_valid_requests(self):
        sys.path.insert(0, "scripts")
        import simulate_traffic as sim
        marginals, categories = sim.load_marginals("configs/drift_reference_profile.json",
                                                   "reports/eda/numeric_summary.csv")
        rng = random.Random(0)
        for scenario in sim.SCENARIOS:
            for _ in range(200):
                student = sim.make_student(rng, marginals, categories, scenario)
                PredictiveFeatures(**student)
                self.assertLessEqual(student["vle_clicks_last_7_days"], student["vle_clicks_last_14_days"])
                self.assertLessEqual(student["vle_clicks_last_14_days"], student["vle_total_clicks"])
                self.assertEqual(COURSE_CATALOG[student["code_module"]][student["code_presentation"]],
                                 student["module_presentation_length"])


if __name__ == "__main__":
    unittest.main()
