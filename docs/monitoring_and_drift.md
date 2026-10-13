# Monitoring and Drift Detection (Step 2.13)

## 1. Why monitoring is required
Deploying a machine learning model is not the end of its lifecycle. Once in production, the data distributions can shift, rendering predictions inaccurate (data drift), and operational characteristics like latency or failure rates can degrade. We must monitor the system to maintain reliability, fairness, and prediction quality over time.

## 2. What is monitored
- **Application health**: Service availability, latency, and error rates.
- **Prediction distribution**: How the model is classifying students across risk tiers.
- **Data drift**: Statistical shifts in the 21 predictive features.
- **Fairness metrics**: Group-wise disparities when sensitive attributes are present in the batch.

## 3. Application metrics
The FastAPI application exposes a `/metrics` endpoint compatible with Prometheus. It tracks:
- `student_dropout_prediction_requests_total`: Total count of inference requests.
- `student_dropout_prediction_errors_total`: Count of failed inference requests.
- `student_dropout_prediction_latency_seconds`: Histogram of prediction request durations.

## 4. Prediction monitoring
Prediction monitoring tracks the distribution of predictions in a given batch. Key metrics include the mean, median, min, and max predicted probabilities, as well as the proportion of students mapped to `LOW`, `MODERATE`, `HIGH`, and `CRITICAL` risk tiers. It also calculates the total human review rate based on the intervention configurations.

## 5. Data drift
Data drift refers to changes in the distribution of the 21 predictive features compared to the reference dataset used during training. We monitor both numerical and categorical features.

## 6. PSI (Population Stability Index)
For numerical features, we calculate the Population Stability Index (PSI). The dataset is divided into 10 buckets based on the reference distribution. The frequency of data points in these buckets is compared against the current batch to produce a single stability score.

## 7. Categorical drift (Total Variation Distance)
For categorical features (e.g., `highest_education`, `code_module`), we calculate the Total Variation Distance (TVD). This represents half the sum of absolute differences in category frequencies between the reference and current datasets.

## 8. Fairness monitoring
Fairness monitoring measures disparities across subgroups based on sensitive attributes (`gender`, `disability`, `age_band`, `region`, `imd_band`). 

## 9. Reference data
The reference dataset for monitoring is strictly `data/processed/splits/development_train.parquet`. The locked `test.parquet` and `final_holdout.parquet` are strictly reserved for final model evaluations and are never used as a baseline for production drift monitoring.

## 10. Drift thresholds
We use the following documented heuristics to flag drift:
- **PSI (Numerical)**:
  - `< 0.10`: No meaningful drift
  - `0.10 – < 0.25`: Moderate drift
  - `>= 0.25`: Substantial drift
- **TVD (Categorical)**:
  - `< 0.05`: No meaningful drift
  - `0.05 – < 0.15`: Moderate drift
  - `>= 0.15`: Substantial drift

## 11. Difference between drift and model degradation
Data drift implies that the inputs to the model have changed structurally. However, **drift does not automatically mean model degradation**. If the relationship between the drifted features and the target variable remains stable, the model's accuracy might still be perfect. Drift acts as an early warning indicator for investigation, not a definitive failure state.

## 12. Difference between prediction-only and delayed-outcome fairness monitoring
- **Prediction-only monitoring**: When the true outcomes (`is_withdrawn`) are not yet known, we can only monitor the **selection rate** (e.g., the proportion of a subgroup flagged for intervention). 
- **Delayed-outcome monitoring**: Once the semester finishes and the true labels become available, we can compute full classification metrics like True Positive Rate (TPR), False Positive Rate (FPR), precision, and recall per subgroup.

## 13. Limitations
- **No Causal Assumptions**: Monitoring correlations and feature drifts does not explain *why* the data shifted.
- **Small Sample Sizes**: Drift and fairness statistics calculated on very small batches are inherently noisy and unreliable. Fairness monitoring specifically suppresses reporting for groups with fewer than 30 samples.
- **Simulation**: The current evaluation script (`evaluate_monitoring.py`) runs a simulated batch using the validation dataset. It does not represent live production traffic.

## 14. Dashboard and Alerting

A lightweight operational monitoring dashboard and alert system are configured using **Prometheus** and **Grafana**. 

### How to Start the Dashboard Locally
Ensure Docker is installed, then run the monitoring stack from the project root:
```bash
docker-compose -f docker-compose.monitoring.yml up -d
```
- **Grafana Dashboard**: Accessible at [http://localhost:3000](http://localhost:3000) (Login: anonymous/viewer enabled, or admin/admin). The **MLOps Prediction Dashboard** is automatically provisioned and displays live application metrics.
- **Prometheus**: Accessible at [http://localhost:9090](http://localhost:9090).

### Dashboard Panels & Metric Sources
The Grafana dashboard visualizes data sourced directly from the FastAPI `/metrics` endpoint:
- **Prediction Request Rate**: Live requests per second (computed from `student_dropout_prediction_requests_total`).
- **Prediction Error Rate**: Live errors per second (computed from `student_dropout_prediction_errors_total`).
- **Prediction Latency**: 50th and 95th percentiles of response latency in seconds (computed from `student_dropout_prediction_latency_seconds_bucket`).

**Important Note on Dashboard Scope**: Live application metrics are displayed in real-time. Complex data validations such as **Concept/Data Drift** and **Fairness Monitoring** require batch aggregations and historical comparisons. They are not displayed as live Prometheus metrics to avoid blocking prediction traffic. Instead, they remain batch-generated reports logged to MLflow or written to disk.

### Alerts
Prometheus is configured with specific Alert Rules (defined in `monitoring/prometheus/alerts.yml`):
- **HighErrorRate (Critical)**: Triggers if more than 10% of prediction requests fail over a 1-minute window.
- **HighLatency (Warning)**: Triggers if the 95th percentile prediction latency exceeds 1.0 second over a 1-minute window.
- **InstanceDown (Critical)**: Triggers if the FastAPI prediction instance (`host.docker.internal:8000`) is unreachable for 1 minute.

*Note: AlertManager is not configured for email/Slack notifications in this local demonstration. Alerts are evaluated and visible directly within the Prometheus UI under the "Alerts" tab.*

### Stopping the Services
To stop the monitoring stack without losing dashboard configurations (which are stateless and provisioned):
```bash
docker-compose -f docker-compose.monitoring.yml down
```

## 15. Future extensions
This monitoring framework is designed to integrate into standard observability stacks. Application metrics can be scraped by Prometheus and visualized in Grafana. The Python-based batch scripts can be orchestrated via Apache Airflow or CI/CD pipelines to run periodically on new data exports, enabling automated alerting for substantial drift or fairness violations.

## 16. Update: live drift and the v2 dashboard
Section 14's "three panels" and "drift is batch-only" describe the original Step 2.13 setup.
Version 2.0 adds an in-process rolling window (last 2,000 predictions) that computes PSI/TVD drift
against a reference profile of the training split and exports it to Prometheus at scrape time,
offline evaluation results exported as gauges, six additional alert rules, and a 66-panel Grafana
dashboard generated from `monitoring/grafana/build_dashboard.py`. The batch evaluation in
`evaluate_monitoring.py` is unchanged. See
[web_platform_and_observability.md](web_platform_and_observability.md).
