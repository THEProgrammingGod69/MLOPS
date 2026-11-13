---
title: Student Dropout Early Warning
emoji: 🎓
colorFrom: red
colorTo: gray
sdk: docker
app_port: 8080
pinned: false
license: mit
short_description: Day-28 dropout risk, 50% alerts in Grafana, any-format intake
---

# The Early Warning: student dropout risk at day 28

A fairness-aware early-warning system trained on the Open University Learning Analytics Dataset
(Kuzilek, Hlosta and Zdrahal, *Scientific Data* 4:170171, 2017, CC BY 4.0).

| Path | What it is |
|---|---|
| `/ui/` | Web app: alert desk, case file with rescue plans, intake for any institution's data, cohort lab |
| `/grafana/d/mlops-monitoring` | Grafana: students at 50 % or higher risk, service health, drift, fairness |
| `/prometheus/` | Prometheus with the `StudentDropoutRiskAbove50` alert rule |
| `/docs` | FastAPI reference |

Live traffic is simulated. Source: https://github.com/THEProgrammingGod69/MLOPS
