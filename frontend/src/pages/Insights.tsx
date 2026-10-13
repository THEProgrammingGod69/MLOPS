import { useMemo, useState } from "react";
import { Award, Info } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../lib/api";
import { int, METRIC_LABEL, MODEL_LABEL, num, pct, titleCase } from "../lib/format";
import { useApi } from "../lib/hooks";
import { CHART_INIT, TIER_COLOR, TIER_LABEL, useChartPalette } from "../lib/theme";
import type { RiskTier, Row } from "../lib/types";
import { Card, ChartTooltip, Empty, ErrorState, Legend, Loading, Segmented } from "../components/ui";

const MODELS = ["lr", "rf", "xgb"];
const COMPARE_METRICS = ["roc_auc", "pr_auc", "f1", "recall", "precision", "accuracy"];

export default function Insights() {
  const palette = useChartPalette();
  const models = useApi(api.insightsModels);
  const explain = useApi(api.insightsExplainability);
  const interventions = useApi(api.insightsInterventions);
  const pipeline = useApi(api.insightsPipeline);
  const card = useApi(api.model);
  const [split, setSplit] = useState<"validation" | "test">("test");
  const [view, setView] = useState<"chart" | "table">("chart");

  const modelColor = (m: string) => palette.series[MODELS.indexOf(m)];
  const comparison = useMemo(() => {
    const rows = (models.data?.comparison ?? []).filter((r) => r.split === split);
    return COMPARE_METRICS.map((metric) => {
      const entry: Record<string, string | number> = { metric: METRIC_LABEL[metric] ?? metric };
      for (const m of MODELS) {
        const hit = rows.find((r) => r.model === m && r.metric === metric);
        if (hit) entry[m] = hit.value;
      }
      return entry;
    });
  }, [models.data, split]);

  // Precision is undefined once a threshold raises no alerts; leave a gap instead of plotting 0.
  const sweep = (models.data?.risk_threshold_sweep ?? []).map((r) => ({
    threshold: Number(r.risk_threshold),
    precision: Number(r.alert_count) > 0 ? Number(r.precision) : null,
    recall: Number(r.recall),
    f1: Number(r.alert_count) > 0 ? Number(r.f1) : null,
  }));
  const cuts = card.data?.risk_tiers
    ? [card.data.risk_tiers.low.max_probability, card.data.risk_tiers.moderate.max_probability, card.data.risk_tiers.high.max_probability]
    : [0.2, 0.3, 0.5];
  const tiers = (interventions.data?.tiers ?? []).map((r: Row) => ({
    tier: r.risk_tier as RiskTier, name: TIER_LABEL[r.risk_tier as RiskTier], rate: Number(r.withdrawal_rate),
    count: Number(r.count), share: Number(r.percentage) / 100,
  }));
  const shap = (explain.data?.shap ?? []).slice(0, 15);
  const calibration = models.data?.calibration ?? [];
  const bestBrier = Math.min(...calibration.map((r) => Number(r.brier_score)));
  const inverted = (models.data?.calibration_audit ?? []).filter((r) => r.ranking_inverted === true);
  const runs = pipeline.data?.runs ?? [];
  const run = runs[runs.length - 1];

  const loadingAny = models.loading || explain.loading || interventions.loading;
  const errorAny = models.error || explain.error || interventions.error;

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Model insights</h1>
          <p className="page-desc">
            Offline evaluation behind the deployed model: how it compares with the baselines, where the risk tiers sit
            on the precision–recall trade-off, what drives predictions globally, and how well calibrated it is.
            Values come from the batch reports in <span className="mono">reports/</span>.
          </p>
        </div>
      </div>

      {errorAny && <div className="mb-16"><ErrorState message={errorAny} /></div>}
      {loadingAny ? <Loading /> : (
        <>
          <div className="grid grid-3 mb-16">
            <Card title="Baseline comparison" subtitle={`Three candidate models on the ${split} split`} className="span-2"
              actions={<>
                <Segmented label="Data split" value={split} onChange={setSplit}
                  options={[{ value: "validation", label: "Validation" }, { value: "test", label: "Test" }]} />
                <Segmented label="View" value={view} onChange={setView}
                  options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]} />
              </>}>
              {view === "chart" ? (
                <>
                  <div className="chart" style={{ height: 270 }}>
                    <ResponsiveContainer initialDimension={CHART_INIT}>
                      <BarChart data={comparison} margin={{ top: 8, right: 8, left: -18, bottom: 0 }} barGap={2} barCategoryGap="22%">
                        <CartesianGrid vertical={false} stroke={palette.grid} />
                        <XAxis dataKey="metric" tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
                        <YAxis domain={[0, 1]} tickLine={false} axisLine={false} tick={{ fill: palette.muted }} />
                        <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }} content={<ChartTooltip />} />
                        {MODELS.map((m) => (
                          <Bar key={m} dataKey={m} name={MODEL_LABEL[m]} fill={modelColor(m)} radius={[4, 4, 0, 0]} maxBarSize={26} isAnimationActive={false} />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <Legend items={MODELS.map((m) => ({ label: `${MODEL_LABEL[m]}${m === "xgb" ? " (deployed)" : ""}`, color: modelColor(m) }))} />
                </>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Metric</th>{MODELS.map((m) => <th key={m} className="r">{MODEL_LABEL[m]}</th>)}</tr></thead>
                    <tbody>
                      {comparison.map((row) => {
                        const best = Math.max(...MODELS.map((m) => Number(row[m] ?? -1)));
                        return (
                          <tr key={String(row.metric)}>
                            <td>{row.metric}</td>
                            {MODELS.map((m) => (
                              <td key={m} className="r num" style={{ fontWeight: Number(row[m]) === best ? 700 : 400 }}>{num(Number(row[m]))}</td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            <Card title="Latest automated pipeline run" subtitle={run ? `${run.report_file}` : "No runs found"}>
              {!run ? <Empty title="No pipeline reports" /> : (
                <>
                  <dl className="kv">
                    <dt>Executed</dt><dd className="mono">{run.execution_timestamp}</dd>
                    <dt>Training rows</dt><dd>{int(Number(run.data_quality.train_rows))}</dd>
                    <dt>Validation rows</dt><dd>{int(Number(run.data_quality.val_rows))}</dd>
                    <dt>Positive rate</dt><dd>{pct(Number(run.data_quality.val_positive_rate))}</dd>
                    <dt>ROC AUC / PR AUC</dt><dd>{num(run.validation_metrics.val_roc_auc)} / {num(run.validation_metrics.val_pr_auc)}</dd>
                    <dt>Run time</dt><dd>{run.execution_time_seconds}s</dd>
                  </dl>
                  <div className="divider" />
                  <div className="stat-label mb-16" style={{ marginBottom: 8 }}>Validation confusion matrix (threshold 0.5)</div>
                  <div className="grid grid-2" style={{ gap: 6 }}>
                    {([["TN", "val_true_negatives"], ["FP", "val_false_positives"], ["FN", "val_false_negatives"], ["TP", "val_true_positives"]] as const).map(([k, key]) => (
                      <div key={k} className="card" style={{ padding: "8px 10px", boxShadow: "none", background: "var(--surface-2)" }}>
                        <div className="muted" style={{ fontSize: 11.5 }}>{k}</div>
                        <div style={{ fontWeight: 700, fontSize: 18 }}>{int(run.validation_metrics[key])}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Card>
          </div>

          <div className="grid grid-2 mb-16">
            <Card title="Threshold trade-off" subtitle="Validation precision, recall and F1 if one probability cut-off raised the alert; dashed lines mark the tier boundaries">
              <div className="chart" style={{ height: 270 }}>
                <ResponsiveContainer initialDimension={CHART_INIT}>
                  <LineChart data={sweep} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke={palette.grid} />
                    <XAxis dataKey="threshold" type="number" domain={[0, 0.95]} ticks={[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]}
                      tickFormatter={(v: number) => v.toFixed(1)} tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
                    <YAxis domain={[0, 1]} tickLine={false} axisLine={false} tick={{ fill: palette.muted }} />
                    {cuts.map((c, i) => (
                      <ReferenceLine key={c} x={c} stroke={TIER_COLOR[(["MODERATE", "HIGH", "CRITICAL"] as RiskTier[])[i]]} strokeDasharray="4 4"
                        label={{ value: TIER_LABEL[(["MODERATE", "HIGH", "CRITICAL"] as RiskTier[])[i]], position: "insideTopRight", fill: palette.muted, fontSize: 11 }} />
                    ))}
                    <Tooltip content={<ChartTooltip title={(l) => `Threshold ${Number(l).toFixed(2)}`} />} />
                    <Line type="linear" dataKey="precision" name="Precision" stroke={palette.series[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line type="linear" dataKey="recall" name="Recall" stroke={palette.series[1]} strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line type="linear" dataKey="f1" name="F1" stroke={palette.series[2]} strokeWidth={2} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <Legend items={[{ label: "Precision", color: palette.series[0] }, { label: "Recall", color: palette.series[1] }, { label: "F1", color: palette.series[2] }]} />
            </Card>

            <Card title="Do the tiers separate risk?" subtitle="Observed withdrawal rate per tier on the validation split">
              {tiers.length === 0 ? <Empty title="No tier report" /> : (
                <>
                  <div className="chart" style={{ height: 230 }}>
                    <ResponsiveContainer initialDimension={CHART_INIT}>
                      <BarChart data={tiers} margin={{ top: 22, right: 8, left: -14, bottom: 0 }}>
                        <CartesianGrid vertical={false} stroke={palette.grid} />
                        <XAxis dataKey="name" tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
                        <YAxis domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} tickLine={false} axisLine={false} tick={{ fill: palette.muted }} />
                        <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }} content={<ChartTooltip format={(v) => pct(v)} />} />
                        <Bar dataKey="rate" name="Withdrawal rate" radius={[4, 4, 0, 0]} maxBarSize={64} isAnimationActive={false}
                          label={{ position: "top", fill: palette.text, fontSize: 12, formatter: (v: unknown) => pct(Number(v), 0) }}>
                          {tiers.map((t) => <Cell key={t.tier} fill={TIER_COLOR[t.tier]} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="grid grid-4" style={{ gap: 8, marginTop: 8 }}>
                    {tiers.map((t) => (
                      <div key={t.tier} style={{ fontSize: 12 }}>
                        <div className="muted">{t.name}</div>
                        <div className="num"><strong>{int(t.count)}</strong> · {pct(t.share)}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Card>
          </div>

          <div className="grid grid-2">
            <Card title="Global feature importance" subtitle="Mean |SHAP| on the validation set, top 15 transformed features">
              {shap.length === 0 ? <Empty title="No SHAP report" /> : (
                <div className="chart" style={{ height: 15 * 26 + 40 }}>
                  <ResponsiveContainer initialDimension={CHART_INIT}>
                    <BarChart data={shap} layout="vertical" margin={{ top: 0, right: 16, left: 4, bottom: 0 }} barCategoryGap={4}>
                      <CartesianGrid horizontal={false} stroke={palette.grid} />
                      <XAxis type="number" tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
                      <YAxis type="category" dataKey="label" width={250} tickLine={false} axisLine={false} tick={{ fill: palette.text, fontSize: 12 }} interval={0} />
                      <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }} content={<ChartTooltip format={(v) => v.toFixed(4)} />} />
                      <Bar dataKey="mean_abs_shap" name="Mean |SHAP|" fill={palette.series[0]} radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            <Card title="Calibration" subtitle="Lower Brier score and ECE are better; the uncalibrated XGBoost is served">
              {calibration.length === 0 ? <Empty title="No calibration report" /> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Model</th><th>Method</th><th className="r">Brier</th><th className="r">ECE</th><th className="r">Log loss</th><th className="r">ROC AUC</th></tr></thead>
                    <tbody>
                      {calibration.map((r) => (
                        <tr key={`${r.model}-${r.calibration_method}`}>
                          <td className="nowrap">{String(r.model).toUpperCase()}</td>
                          <td>{titleCase(String(r.calibration_method))}
                            {Number(r.brier_score) === bestBrier && <span className="badge badge-accent" style={{ marginLeft: 6 }}><Award size={11} /> best</span>}
                          </td>
                          <td className="r num">{num(Number(r.brier_score), 4)}</td>
                          <td className="r num">{num(Number(r.ece), 4)}</td>
                          <td className="r num">{num(Number(r.log_loss), 3)}</td>
                          <td className="r num">{num(Number(r.roc_auc), 3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {inverted.length > 0 && (
                <div className="callout callout-warn mt-16">
                  <Info size={15} />
                  <span>
                    The integrated audit found {inverted.map((r) => `${titleCase(String(r.calibration_method))} calibration (ROC AUC ${num(Number(r.roc_auc), 2)})`).join(" and ")}{" "}
                    inverting the risk ranking, which is why the service keeps the uncalibrated model and its probability-based tiers.
                  </span>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
