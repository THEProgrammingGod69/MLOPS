import { Activity, AlertTriangle, CheckCircle2, ExternalLink, Gauge, Info, Timer } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { int, ms, num, pct, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";
import { CHART_INIT, STATUS, useChartPalette } from "../lib/theme";
import type { DriftFeature, DriftStatus } from "../lib/types";
import { Card, ChartTooltip, Empty, ErrorState, Legend, Loading, StatTile, TierBadge } from "../components/ui";

const STATUS_COLOR: Record<DriftStatus, string> = {
  "no meaningful drift": STATUS.good,
  "moderate drift": STATUS.warning,
  "substantial drift": STATUS.critical,
};

function DriftBadge({ status }: { status: DriftStatus }) {
  const cls = status === "no meaningful drift" ? "tier-LOW" : status === "moderate drift" ? "tier-MODERATE" : "tier-CRITICAL";
  const icon = status === "no meaningful drift" ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />;
  return <span className={`badge ${cls}`}>{icon}{status === "no meaningful drift" ? "Stable" : status === "moderate drift" ? "Moderate" : "Substantial"}</span>;
}

export default function Monitoring() {
  const palette = useChartPalette();
  const drift = useApi(api.monitoringDrift, 5000);
  const summary = useApi(api.monitoringSummary, 5000);
  const recent = useApi(() => api.monitoringRecent(25), 5000);
  const meta = useApi(api.meta);

  const d = drift.data;
  const s = summary.data;
  const psi = (d?.features ?? []).filter((f) => f.metric === "PSI");
  const tvd = (d?.features ?? []).filter((f) => f.metric === "TVD");
  const progress = d ? Math.min(1, d.window_size / d.min_samples) : 0;
  const grafana = meta.data?.links.grafana;

  const driftChart = (rows: DriftFeature[], thresholds: [number, number], label: string) => (
    <>
      <div className="chart" style={{ height: rows.length * 28 + 50 }}>
        <ResponsiveContainer initialDimension={CHART_INIT}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 18, left: 4, bottom: 0 }} barCategoryGap={4}>
            <CartesianGrid horizontal={false} stroke={palette.grid} />
            <XAxis type="number" domain={[0, (max: number) => Math.max(max, thresholds[1] * 1.3)]} tickFormatter={(v: number) => v.toFixed(2)}
              tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
            <YAxis type="category" dataKey="feature" width={200} tickLine={false} axisLine={false} tick={{ fill: palette.text, fontSize: 12 }} interval={0} />
            <ReferenceLine x={thresholds[0]} stroke={STATUS.warning} strokeDasharray="4 4" />
            <ReferenceLine x={thresholds[1]} stroke={STATUS.critical} strokeDasharray="4 4" />
            <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }} content={<ChartTooltip format={(v) => `${label} ${v.toFixed(4)}`} />} />
            <Bar dataKey="value" name={label} radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false}>
              {rows.map((r) => <Cell key={r.feature} fill={STATUS_COLOR[r.status]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[
        { label: `Stable (< ${thresholds[0]})`, color: STATUS.good },
        { label: `Moderate (${thresholds[0]}–${thresholds[1]})`, color: STATUS.warning },
        { label: `Substantial (≥ ${thresholds[1]})`, color: STATUS.critical },
      ]} />
    </>
  );

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Live monitoring</h1>
          <p className="page-desc">
            Data drift and service health computed from a rolling window of the most recent predictions. The same
            signals are exported on <span className="mono">/metrics</span> and charted over time in Grafana.
          </p>
        </div>
        <div className="page-actions">
          {grafana && <a className="btn btn-primary" href={`${grafana}/d/mlops-monitoring`} target="_blank" rel="noreferrer"><Gauge size={14} /> Open Grafana dashboard <ExternalLink size={12} /></a>}
        </div>
      </div>

      {(drift.error || summary.error) && <div className="mb-16"><ErrorState message={drift.error ?? summary.error ?? ""} /></div>}

      <div className="grid grid-4 mb-16">
        <StatTile label="Rolling window" icon={<Activity size={16} />} value={d ? `${int(d.window_size)} / ${int(d.window_capacity)}` : "—"}
          foot="most recent students scored" />
        <StatTile label="Drifting features" icon={<AlertTriangle size={16} />}
          value={d?.ready ? int(d.features.filter((f) => f.status !== "no meaningful drift").length) : "—"}
          foot={d?.ready ? `of ${d.features.length} tracked` : "waiting for enough samples"} />
        <StatTile label="Latency p95 / p99" icon={<Timer size={16} />} value={ms(s?.window.latency_ms.p95)}
          foot={s ? `p99 ${ms(s.window.latency_ms.p99)} · p50 ${ms(s.window.latency_ms.p50)}` : " "} />
        <StatTile label="Failed requests" icon={<Info size={16} />} value={s ? int(s.totals.errors) : "—"}
          foot={s ? `${int(s.totals.predictions)} successful predictions` : " "} />
      </div>

      {d && (
        <div className={`callout ${d.reference.approximate ? "callout-warn" : ""} mb-16`}>
          <Info size={15} />
          <span>
            Reference profile: <strong>{d.reference.source ?? "none"}</strong>
            {d.reference.n_rows ? ` (${int(d.reference.n_rows)} rows)` : ""}
            {d.reference.generated_at ? `, generated ${d.reference.generated_at}` : ""}.{" "}
            {d.reference.approximate
              ? <>This is the quartile approximation from the EDA report, so only high-cardinality features are tracked. Run{" "}
                <span className="mono">python -m src.monitoring.build_reference_profile</span> with the DVC data to track all 21 features exactly.</>
              : <>Numeric features use PSI over training deciles; categorical features use total variation distance.</>}
          </span>
        </div>
      )}

      {drift.loading ? <Loading /> : !d?.ready ? (
        <Card className="mb-16">
          <Empty title="Collecting a statistically meaningful window" icon={<Activity size={28} />}>
            Drift is reported once {int(d?.min_samples)} predictions are in the window (categorical features need{" "}
            {int(d?.min_samples_categorical)}), so sampling noise stays well below the alert thresholds.
            <div className="progress mt-16" aria-label="Window fill"><span style={{ width: `${progress * 100}%` }} /></div>
            <div className="mt-8 num">{int(d?.window_size)} / {int(d?.min_samples)}</div>
            <div className="mt-8">Tip: <span className="mono">python scripts/simulate_traffic.py</span> generates realistic traffic.</div>
          </Empty>
        </Card>
      ) : (
        <div className="grid grid-2 mb-16">
          <Card title="Numeric drift (PSI)" subtitle={`Population stability index vs reference; ${d.thresholds.psi[0]} / ${d.thresholds.psi[1]} thresholds`}>
            {psi.length ? driftChart(psi, d.thresholds.psi, "PSI") : <Empty title="No numeric features tracked" />}
          </Card>
          <Card title="Categorical drift (TVD)" subtitle={`Total variation distance; ${d.thresholds.tvd[0]} / ${d.thresholds.tvd[1]} thresholds`}>
            {tvd.length ? driftChart(tvd, d.thresholds.tvd, "TVD") : (
              <Empty title={d.reference.approximate ? "Not in the approximate profile" : "Warming up"}>
                {d.reference.approximate
                  ? "The EDA fallback has no category frequencies. Build the profile from the training split to enable this."
                  : `Categorical drift needs ${int(d.min_samples_categorical)} samples in the window.`}
              </Empty>
            )}
          </Card>
        </div>
      )}

      {d?.ready && (
        <Card title="Feature drift detail" className="mb-16" flush>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Feature</th><th>Statistic</th><th className="r">Value</th><th>Status</th><th className="r">Window mean</th><th className="r">Reference mean</th><th className="r">Missing (window / ref)</th></tr>
              </thead>
              <tbody>
                {d.features.map((f) => (
                  <tr key={f.feature}>
                    <td className="mono">{f.feature}</td>
                    <td>{f.metric}</td>
                    <td className="r num">{num(f.value, 4)}</td>
                    <td><DriftBadge status={f.status} /></td>
                    <td className="r num">{num(f.window_mean, 2)}</td>
                    <td className="r num">{num(f.reference_mean, 2)}</td>
                    <td className="r num">{pct(f.window_missing_rate)} / {pct(f.reference_missing_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title="Prediction feed" subtitle="Latest 25 scored students" flush>
        {recent.loading ? <Loading /> : !recent.data?.items.length ? <Empty title="No predictions yet" /> : (
          <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
            <table className="table">
              <thead><tr><th>When</th><th>Prediction</th><th>Course</th><th className="r">Risk</th><th>Tier</th><th>Review</th><th>Fairness</th><th>Source</th></tr></thead>
              <tbody>
                {recent.data.items.map((r) => (
                  <tr key={r.prediction_id}>
                    <td className="muted nowrap">{timeAgo(r.timestamp)}</td>
                    <td className="mono">{r.prediction_id}</td>
                    <td className="mono">{r.code_module} {r.code_presentation}</td>
                    <td className="r num">{pct(r.risk_probability)}</td>
                    <td><TierBadge tier={r.risk_tier} /></td>
                    <td>{r.human_review_required ? "Yes" : <span className="muted">No</span>}</td>
                    <td className="secondary" style={{ fontSize: 12 }}>{r.fairness_status === "Applied" ? "Applied" : "Not applied"}</td>
                    <td><span className="badge badge-neutral">{r.source}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
