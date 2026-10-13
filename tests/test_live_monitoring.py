import json
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from src.monitoring.build_reference_profile import (NUMERIC_FEATURES, build_from_dataframe,
                                                    build_from_eda_summary)
from src.monitoring.live_monitor import (LiveMonitor, LiveMonitorCollector, psi_from_profile,
                                         tvd_from_profile)
from src.monitoring.offline_metrics import OfflineMetricsCollector
from src.monitoring.report_store import ReportStore
from tests._tiny_model import synthetic_frame


def _result(probability, tier="LOW", review=False):
    return {"risk_probability": probability, "risk_tier": tier, "human_review_required": review,
            "intervention_level": "monitoring", "fairness_status": "Applied", "prediction_id": "x"}


class TestDriftStatistics(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.reference = pd.DataFrame({"vle_total_clicks": rng.lognormal(5, 1, 5000)})
        self.reference.loc[:499, "vle_total_clicks"] = np.nan
        self.spec = build_from_dataframe(self.reference)["numeric"]["vle_total_clicks"]

    def test_profile_bins_are_consistent(self):
        self.assertAlmostEqual(sum(self.spec["proportions"]), 1.0, places=9)
        self.assertEqual(len(self.spec["proportions"]), len(self.spec["edges"]) + 1)
        self.assertAlmostEqual(self.spec["missing_rate"], 0.1, places=3)

    def test_same_distribution_has_low_psi(self):
        sample = self.reference["vle_total_clicks"].sample(2000, random_state=1).to_numpy()
        self.assertLess(psi_from_profile(sample, self.spec), 0.02)

    def test_shifted_distribution_has_high_psi(self):
        shifted = self.reference["vle_total_clicks"].dropna().to_numpy() * 0.2
        self.assertGreater(psi_from_profile(shifted, self.spec), 0.25)

    def test_missingness_change_is_drift(self):
        all_missing = np.full(1000, np.nan)
        self.assertGreater(psi_from_profile(all_missing, self.spec), 0.25)

    def test_discrete_ties_are_binned_exactly(self):
        df = pd.DataFrame({"num_of_prev_attempts": [0] * 870 + [1] * 100 + [2] * 30})
        spec = build_from_dataframe(df)["numeric"]["num_of_prev_attempts"]
        self.assertLess(psi_from_profile(df["num_of_prev_attempts"].to_numpy(dtype=float), spec), 1e-9)

    def test_tvd(self):
        spec = {"frequencies": {"A": 0.5, "B": 0.5}}
        self.assertAlmostEqual(tvd_from_profile(["A"] * 50 + ["B"] * 50, spec), 0.0)
        self.assertAlmostEqual(tvd_from_profile(["A"] * 100, spec), 0.5)


class TestReferenceProfileBuilders(unittest.TestCase):
    def test_from_dataframe_covers_features(self):
        profile = build_from_dataframe(synthetic_frame(500))
        self.assertFalse(profile["approximate"])
        self.assertEqual(set(profile["numeric"]), set(NUMERIC_FEATURES))
        self.assertEqual(set(profile["categorical"]), {"highest_education", "code_module", "code_presentation"})

    def test_eda_fallback_only_keeps_safe_features(self):
        profile = build_from_eda_summary()
        self.assertTrue(profile["approximate"])
        self.assertIn("vle_total_clicks", profile["numeric"])
        # Tied quartiles (mostly zeros) cannot be binned without raw data.
        self.assertNotIn("num_of_prev_attempts", profile["numeric"])
        for spec in profile["numeric"].values():
            self.assertTrue(all(b > a for a, b in zip(spec["edges"], spec["edges"][1:])))

    def test_committed_profile_is_valid(self):
        with open("configs/drift_reference_profile.json") as f:
            profile = json.load(f)
        for spec in profile["numeric"].values():
            self.assertAlmostEqual(sum(spec["proportions"]), 1.0, places=6)
            self.assertLessEqual(spec["min"], spec["edges"][0])
            self.assertGreaterEqual(spec["max"], spec["edges"][-1])


class TestLiveMonitor(unittest.TestCase):
    def setUp(self):
        frame = synthetic_frame(3000, seed=3)
        self.profile = build_from_dataframe(frame)
        self.rows = frame.astype(object).where(frame.notna(), None).to_dict(orient="records")
        self.monitor = LiveMonitor(self.profile, window_size=1000, min_samples=500,
                                   min_samples_categorical=800, recent_size=10)

    def _feed(self, rows):
        self.monitor.observe(rows, [_result(0.1) for _ in rows], source="batch")

    def test_no_drift_report_before_warm_up(self):
        self._feed(self.rows[:100])
        self.assertEqual(self.monitor.drift(), [])
        self.assertFalse(self.monitor.summary()["drift"]["ready"])

    def test_categorical_waits_for_its_own_warm_up(self):
        self._feed(self.rows[:600])
        metrics = {d["metric"] for d in self.monitor.drift()}
        self.assertEqual(metrics, {"PSI"})
        self._feed(self.rows[600:900])
        self.assertIn("TVD", {d["metric"] for d in self.monitor.drift()})

    def test_reference_like_traffic_is_quiet(self):
        self._feed(self.rows[2000:3000])
        drifted = [d for d in self.monitor.drift() if d["status"] == "substantial drift"]
        self.assertEqual(drifted, [])

    def test_shifted_traffic_is_flagged(self):
        shifted = [dict(r, vle_total_clicks=(r["vle_total_clicks"] or 0) * 10) for r in self.rows[:1000]]
        self._feed(shifted)
        by_feature = {d["feature"]: d for d in self.monitor.drift()}
        self.assertEqual(by_feature["vle_total_clicks"]["status"], "substantial drift")

    def test_window_stats_and_recent(self):
        self.monitor.observe(self.rows[:4], [_result(0.1), _result(0.25, "MODERATE"),
                                             _result(0.4, "HIGH", True), _result(0.9, "CRITICAL", True)],
                             source="single", latency_seconds=0.01)
        stats = self.monitor.window_stats()
        self.assertEqual(stats["size"], 4)
        self.assertAlmostEqual(stats["human_review_rate"], 0.5)
        self.assertAlmostEqual(sum(stats["tier_share"].values()), 1.0)
        self.assertEqual(sum(stats["risk_histogram"]), 4)
        recent = self.monitor.recent(2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["risk_tier"], "CRITICAL")  # newest first
        self.assertEqual(self.monitor.summary()["totals"]["tiers"]["HIGH"], 1)

    def test_window_is_bounded(self):
        self._feed(self.rows[:1500])
        self.assertEqual(self.monitor.window_stats()["size"], 1000)
        self.assertEqual(len(self.monitor.recent(100)), 10)

    def test_collector_emits_drift_gauges(self):
        self._feed(self.rows[:1000])
        names = {family.name for family in LiveMonitorCollector(self.monitor).collect()}
        for expected in ("student_dropout_window_predictions", "student_dropout_feature_drift_score",
                         "student_dropout_feature_drift_status", "student_dropout_drifted_features",
                         "student_dropout_window_tier_share"):
            self.assertIn(expected, names)


class TestReportStoreAndOfflineMetrics(unittest.TestCase):
    def setUp(self):
        self.store = ReportStore("reports")

    def test_model_comparison_long_format(self):
        rows = self.store.model_comparison()
        keys = {(r["model"], r["split"], r["metric"]) for r in rows}
        self.assertIn(("xgb", "test", "roc_auc"), keys)
        self.assertEqual(len(rows), 3 * 3 * 8)

    def test_records_are_json_safe(self):
        for rows in (self.store.group_metrics(), self.store.fairness_disparity(), self.store.mitigation()):
            json.dumps(rows, allow_nan=False)  # NaN would raise

    def test_missing_reports_dir_degrades_gracefully(self):
        empty = ReportStore(tempfile.mkdtemp())
        self.assertEqual(empty.model_comparison(), [])
        self.assertEqual(empty.pipeline_runs(), [])
        families = list(OfflineMetricsCollector(empty).collect())
        self.assertTrue(all(len(f.samples) == 0 or f.name.endswith("pipeline_runs") for f in families))

    def test_offline_collector_publishes_reports(self):
        families = {f.name: f for f in OfflineMetricsCollector(self.store).collect()}
        model = families["student_dropout_offline_model_metric"]
        values = {tuple(sorted(s.labels.items())): s.value for s in model.samples}
        key = (("metric", "roc_auc"), ("model", "xgb"), ("split", "test"))
        self.assertAlmostEqual(values[key], 0.7051310195178536)
        self.assertGreater(len(families["student_dropout_offline_fairness_disparity"].samples), 0)
        self.assertGreater(len(families["student_dropout_offline_shap_importance"].samples), 0)

    def test_report_cache_refreshes_on_change(self):
        directory = tempfile.mkdtemp()
        os.makedirs(os.path.join(directory, "explainability"))
        path = os.path.join(directory, "explainability", "shap_global_importance.csv")
        pd.DataFrame({"feature": ["a"], "mean_abs_shap": [1.0], "rank": [1]}).to_csv(path, index=False)
        store = ReportStore(directory)
        self.assertEqual(len(store.shap_importance()), 1)
        pd.DataFrame({"feature": ["a", "b"], "mean_abs_shap": [1.0, 0.5], "rank": [1, 2]}).to_csv(path, index=False)
        os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
        self.assertEqual(len(store.shap_importance()), 2)


if __name__ == "__main__":
    unittest.main()
