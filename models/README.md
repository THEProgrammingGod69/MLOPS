# Model artifacts

Trained artifacts are produced by the pipeline (`src/models/train_baselines.py`,
`src/fairness/mitigate.py`) and are not tracked by default. The API serves:

| File | Required | Purpose |
|---|---|---|
| `baseline/xgb_pipeline.pkl` | yes | XGBoost risk pipeline |
| `mitigated/xgb_threshold_optimizer_gender.pkl` | no | Fairness post-processor (ThresholdOptimizer) |

To deploy from GitHub (e.g. the Render Blueprint), commit them explicitly:

```bash
git add -f models/baseline/xgb_pipeline.pkl models/mitigated/xgb_threshold_optimizer_gender.pkl
git commit -m "chore: add served model artifacts"
```

Without them the service still starts; `/api/v1/health` and the UI report "Model not loaded".
