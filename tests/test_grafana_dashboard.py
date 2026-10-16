"""Static checks for the Grafana dashboard and Prometheus alert rules.

Catches the failure modes that otherwise only show up as empty panels: a query that
references a metric the API never exports, a datasource uid that does not resolve,
overlapping panels, or a committed JSON that no longer matches its generator.
"""
import json
import os
import re
import sys
import unittest

import yaml
from prometheus_client import REGISTRY

DASHBOARD = "monitoring/grafana/dashboards/prediction_dashboard.json"
ALERTS = "monitoring/prometheus/alerts.yml"
DATASOURCE = "monitoring/grafana/provisioning/datasources/prometheus.yml"
METRIC_TOKEN = re.compile(r"\b(student_dropout_[a-z0-9_]+|process_[a-z_]+|python_[a-z_]+|up|ALERTS)\b")
EXTERNAL = {"up", "ALERTS"}  # produced by Prometheus itself


def exported_sample_names():
    """Every sample name the API can expose, including the scrape-time collectors."""
    import src.api.telemetry  # noqa: F401  registers the live and offline collectors
    from src.monitoring.build_reference_profile import build_from_dataframe
    from src.monitoring.live_monitor import LiveMonitor, LiveMonitorCollector
    from tests._tiny_model import synthetic_frame

    names = {s.name for family in REGISTRY.collect() for s in family.samples}
    frame = synthetic_frame(1600, seed=4)
    monitor = LiveMonitor(build_from_dataframe(frame), window_size=1600, min_samples=10, min_samples_categorical=10)
    rows = frame.astype(object).where(frame.notna(), None).to_dict(orient="records")
    monitor.observe(rows, [{"risk_probability": 0.4, "risk_tier": "HIGH", "human_review_required": True,
                            "intervention_level": "x"} for _ in rows], source="batch")
    names |= {s.name for family in LiveMonitorCollector(monitor).collect() for s in family.samples}
    # Labelled families have no samples until traffic arrives; derive their exposition names.
    suffixes = {"counter": ("_total",), "histogram": ("_bucket", "_count", "_sum"), "gauge": ("",), "info": ("_info",)}
    for family in REGISTRY.collect():
        names |= {family.name + suffix for suffix in suffixes.get(family.type, ("",))}
    return names


def walk_targets(panels):
    for panel in panels:
        yield from panel.get("targets", [])
        yield from walk_targets(panel.get("panels", []))


class TestGrafanaDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DASHBOARD) as f:
            cls.dashboard = json.load(f)
        cls.panels = cls.dashboard["panels"]
        cls.exported = exported_sample_names()

    def test_committed_json_matches_generator(self):
        sys.path.insert(0, "monitoring/grafana")
        import build_dashboard
        self.assertEqual(build_dashboard.build(), self.dashboard,
                         "Run `python monitoring/grafana/build_dashboard.py` and commit the result")

    def test_panel_ids_unique_and_layout_valid(self):
        ids = [p["id"] for p in self.panels]
        self.assertEqual(len(ids), len(set(ids)))
        boxes = []
        for p in self.panels:
            g = p["gridPos"]
            self.assertGreaterEqual(g["x"], 0)
            self.assertLessEqual(g["x"] + g["w"], 24, p["title"])
            boxes.append((g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"], p["title"]))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                self.assertFalse(overlap, f"Panels overlap: {a[4]!r} and {b[4]!r}")

    def test_rich_dashboard(self):
        visual = [p for p in self.panels if p["type"] not in ("row", "text")]
        self.assertGreaterEqual(len(visual), 50)
        self.assertGreaterEqual(len({p["type"] for p in visual}), 9)

    def test_datasource_uid_resolves(self):
        with open(DATASOURCE) as f:
            uid = yaml.safe_load(f)["datasources"][0]["uid"]
        variable = next(v for v in self.dashboard["templating"]["list"] if v["name"] == "datasource")
        self.assertEqual(variable["current"]["value"], uid)
        for t in walk_targets(self.panels):
            self.assertEqual(t["datasource"]["uid"], "${datasource}")

    def test_queries_reference_exported_metrics(self):
        exprs = [t["expr"] for t in walk_targets(self.panels)]
        exprs += [a["expr"] for a in self.dashboard["annotations"]["list"] if "expr" in a]
        missing = set()
        for expr in exprs:
            for name in METRIC_TOKEN.findall(expr):
                if name not in EXTERNAL and name not in self.exported:
                    missing.add(name)
        self.assertEqual(missing, set(), f"Dashboard queries reference unknown metrics: {missing}")

    def test_alert_rules_reference_exported_metrics(self):
        with open(ALERTS) as f:
            rules = [r for g in yaml.safe_load(f)["groups"] for r in g["rules"]]
        self.assertGreaterEqual(len(rules), 9)
        for rule in rules:
            self.assertIn(rule["labels"]["severity"], ("critical", "warning", "info"))
            for name in METRIC_TOKEN.findall(rule["expr"]):
                self.assertTrue(name in EXTERNAL or name in self.exported, f"{rule['alert']}: unknown metric {name}")

    def test_compose_files_are_consistent(self):
        with open("docker-compose.yml") as f:
            compose = yaml.safe_load(f)
        self.assertEqual(set(compose["services"]), {"api", "web", "prometheus", "grafana", "traffic"})
        with open("monitoring/prometheus/prometheus.docker.yml") as f:
            prom = yaml.safe_load(f)
        self.assertIn("api:8000", prom["scrape_configs"][0]["static_configs"][0]["targets"])
        self.assertTrue(os.path.exists("frontend/Dockerfile"))

    def test_render_blueprint_is_consistent(self):
        with open("render.yaml") as f:
            services = {s["name"]: s for s in yaml.safe_load(f)["services"]}
        self.assertEqual(len(services), 3)
        for service in services.values():
            self.assertTrue(os.path.exists(service["dockerfilePath"]), service["dockerfilePath"])
            self.assertEqual(service["dockerContext"], ".")
        env = {s: {e["key"]: e.get("value") for e in services[s]["envVars"]} for s in services}
        api, prom, grafana = "mlops-ews-api", "mlops-ews-prometheus", "mlops-ews-grafana"
        self.assertEqual(env[prom]["API_TARGET"], f"{api}.onrender.com")
        self.assertEqual(env[grafana]["PROMETHEUS_URL"], f"https://{prom}.onrender.com")
        self.assertEqual(env[api]["GRAFANA_URL"], f"https://{grafana}.onrender.com")
        admin = next(e for e in services[grafana]["envVars"] if e["key"] == "GF_SECURITY_ADMIN_PASSWORD")
        self.assertTrue(admin.get("generateValue"), "Grafana admin password must not be a fixed value")
        with open("deploy/render/prometheus.yml.template") as f:
            template = f.read()
        self.assertIn("__API_TARGET__", template)
        self.assertIn("__API_SCHEME__", template)


if __name__ == "__main__":
    unittest.main()
