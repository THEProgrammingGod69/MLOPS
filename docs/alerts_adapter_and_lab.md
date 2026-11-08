# Alerts, institution adapter, decision lab and cold starts

## Why the Vercel deployment showed "DOWN"

Measured against the live site: an instance survives a 30-second idle gap and is gone after
60 seconds. Every visit after that boots a new container with an empty Prometheus, and
Prometheus started alongside the API, so its first scrapes failed while the model was still
loading. Those failed scrapes recorded `up = 0`, which the dashboard shows as **DOWN**.
Vercel Daemons are always on but accept no inbound HTTP, so they cannot serve this.

The fix makes a cold start invisible rather than trying to prevent it:

| Step | Effect |
|---|---|
| nginx opens first | The UI renders at once; Grafana and Prometheus show a self-refreshing page until ready |
| Prometheus waits for the API | `up` never records a false 0 |
| `record_history.py` at build, `replay_history.py` at boot (Prometheus remote write) | Every instance opens with about an hour of charts |
| Browser keeps open cases | They are restored whenever the UI notices a new instance |

The replayed hour is real model scoring of simulated students, captured at build time. Anything
after boot is live. Long-term history still needs an always-on host.

## Alerts at 50 %

Any prediction at or above `ALERT_THRESHOLD` (default `0.5`) opens a case, from the case file, a
batch, the adapter or the legacy API. Cases are exported as `student_dropout_alert_open`, which fires
`StudentDropoutRiskAbove50` in `monitoring/prometheus/alerts.yml` and fills the first row of the Grafana
dashboard.

- Student labels are salted pseudonyms (`S-3F9A1C`). The real reference stays in the API response.
- Label cardinality is bounded: 200 user cases and 12 simulator cases.
- Acknowledging a case on the alert desk removes its series.

## Institution data adapter

`POST /api/v1/adapter/inspect` profiles a CSV, TSV, Excel or JSON file and proposes a mapping.
`POST /api/v1/adapter/score` applies it (4 MB, 2,000 rows).

1. **Profile**: numbers, percentages, fractions, dates and letter grades.
2. **Match**: one-to-one assignment over name, type and value plausibility (`src/adapter/vocabulary.py`).
3. **Convert**: GPA/4, CGPA/10, marks/20, letter grades and date differences are rescaled directly.
   Related measures such as attendance or logins use percentile transport onto the training
   distribution. A name that matches with the wrong unit is detected and transported too.
4. **Fill**: unrecorded engagement features inherit the student's engagement percentile.
5. **Disclose**: the Institution Fit Score weights each input by SHAP importance and by how it
   was obtained. 70+ is strong, 45-69 needs caution, below 45 is indicative only.
6. **Validate**: with an outcome column, the raw score is tested (AUC, Brier) and recalibrated.

The adapter makes other data *usable*. It does not prove the model is valid for that institution,
which is what the fit score and local validation are for.

## Decision lab

| Endpoint | What it answers |
|---|---|
| `POST /api/v1/lab/rescue` | The smallest set of student actions that brings risk under the target |
| `POST /api/v1/lab/triage` | Where a fixed number of advisor hours does the most, compared with highest-risk-first |
| `POST /api/v1/lab/stress` | Who would cross the alert line under an LMS outage, exam slump and other shocks |

These report how the model responds to changed inputs. They are not causal estimates.

## Regenerating assets

```bash
python monitoring/grafana/build_dashboard.py
python scripts/make_sample_institutions.py
```
