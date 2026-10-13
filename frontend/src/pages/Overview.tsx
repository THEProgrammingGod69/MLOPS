import { Activity, ArrowRight, Clock, Radar, ShieldAlert, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { duration, int, MODEL_LABEL, ms, pct, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";
import { CHART_INIT, TIER_COLOR, TIER_LABEL, tierForProbability, useChartPalette } from "../lib/theme";
import { RISK_TIERS } from "../lib/types";
import { Card, ChartTooltip, Empty, ErrorState, Legend, Loading, StatTile, TierBadge } from "../components/ui";

const MODEL_METRICS: [string, string][] = [
  ["roc_auc", "ROC AUC"], ["pr_auc", "PR AUC"], ["recall", "Recall"], ["precision", "Precision"], ["specificity", "Specificity"],
];

export default function Overview() {
  const palette = useChartPalette();
  const summary = useApi(api.monitoringSummary, 5000);
  const recent = useApi(() => api.monitoringRecent(8), 5000);
  const model = useApi(api.model);
  const health = useApi(api.health, 15000);

  const s = summary.data;
  const tierData = s
    ? RISK_TIERS.map((t) => ({ tier: t, name: TIER_LABEL[t], value: s.totals.tiers[t] ?? 0 }))
    : [];
  const totalScored = tierData.reduce((acc, d) => acc + d.value, 0);
  const histogram = s
    ? s.window.risk_histogram.map((count, i) => {
        const lo = i * 0.05;
        return { bin: `${Math.round(lo * 100)}–${Math.round((lo + 0.05) * 100)}%`, lo, count, tier: tierForProbability(lo + 0.025) };
      })
    : [];
  const driftLabel = !s
    ? "—"
    : !s.drift.available
      ? "No profile"
      : !s.drift.ready
        ? "Warming up"
        : s.drift.substantial + s.drift.moderate === 0
          ? "Stable"
          : `${s.drift.substantial + s.drift.moderate} drifting`;

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Overview</h1>
          <p className="page-desc">
            Day-28 dropout early warning for Open University modules. Scores arrive from advisors and batch jobs;
            everything on this page updates live from the inference service.
          </p>
        </div>
        <div className="page-actions">
          <a className="btn btn-primary" href="#/assess">Assess a student <ArrowRight size={14} /></a>
          <a className="btn" href="#/batch">Score a cohort</a>
        </div>
      </div>

      {summary.error && <div className="mb-16"><ErrorState message={summary.error} onRetry={summary.reload} /></div>}

      <div className="grid grid-5 mb-16">
        <StatTile label="Students scored" icon={<Users size={16} />} value={s ? int(s.totals.predictions) : "—"}
          foot={s ? `${int(s.totals.single)} single · ${int(s.totals.batch)} batch · up ${duration(s.uptime_seconds)}` : " "} />
        <StatTile label="Human review rate" icon={<ShieldAlert size={16} />} value={pct(s?.window.human_review_rate)}
          foot={s ? `${int(s.totals.human_review)} students routed to an advisor` : " "} />
        <StatTile label="Mean predicted risk" icon={<Radar size={16} />} value={pct(s?.window.mean_risk_probability)}
          foot={s ? `p90 ${pct(s.window.p90_risk_probability)} · last ${int(s.window.size)} scored` : " "} />
        <StatTile label="Latency p95" icon={<Clock size={16} />} value={ms(s?.window.latency_ms.p95)}
          foot={s ? `p50 ${ms(s.window.latency_ms.p50)} · p99 ${ms(s.window.latency_ms.p99)}` : " "} />
        <StatTile label="Data drift" icon={<Activity size={16} />} value={driftLabel}
          foot={s ? (s.drift.ready
            ? `${s.drift.features_tracked} features vs ${s.drift.reference_source}`
            : `${int(s.window.size)} / ${int(s.drift.min_samples)} samples needed`) : " "} />
      </div>

      <div className="grid grid-3 mb-16">
        <Card title="Risk tier mix" subtitle="All students scored since the service started">
          {summary.loading ? <Loading /> : totalScored === 0 ? (
            <Empty title="No predictions yet">Assess a student or upload a cohort to populate this view.</Empty>
          ) : (
            <>
              <div className="chart" style={{ height: 200 }}>
                <ResponsiveContainer initialDimension={CHART_INIT}>
                  <PieChart>
                    <Pie data={tierData} dataKey="value" nameKey="name" innerRadius={58} outerRadius={84}
                      paddingAngle={1.5} stroke={palette.surface} strokeWidth={2} isAnimationActive={false}>
                      {tierData.map((d) => <Cell key={d.tier} fill={TIER_COLOR[d.tier]} />)}
                    </Pie>
                    <Tooltip content={<ChartTooltip format={(v) => `${int(v)} (${pct(v / totalScored)})`} title={(_, p) => String(p[0]?.name ?? "")} />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="stack" style={{ gap: 6 }}>
                {tierData.map((d) => (
                  <div key={d.tier} className="spread">
                    <TierBadge tier={d.tier} />
                    <span className="num secondary">{int(d.value)} · {pct(d.value / totalScored)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>

        <Card title="Predicted risk distribution" subtitle="Rolling window, coloured by the tier each band maps to" className="span-2">
          {summary.loading ? <Loading /> : !s || s.window.size === 0 ? (
            <Empty title="Window is empty">The histogram fills as predictions arrive.</Empty>
          ) : (
            <>
              <div className="chart" style={{ height: 250 }}>
                <ResponsiveContainer initialDimension={CHART_INIT}>
                  <BarChart data={histogram} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap={2}>
                    <CartesianGrid vertical={false} stroke={palette.grid} />
                    <XAxis dataKey="bin" tick={{ fill: palette.muted, fontSize: 11 }} tickLine={false} stroke={palette.axis} interval={1} />
                    <YAxis allowDecimals={false} tick={{ fill: palette.muted }} tickLine={false} axisLine={false} />
                    <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }}
                      content={<ChartTooltip format={(v) => `${int(v)} students`} title={(l) => `Risk ${l}`} />} />
                    <Bar dataKey="count" name="Students" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                      {histogram.map((d) => <Cell key={d.bin} fill={TIER_COLOR[d.tier]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <Legend items={RISK_TIERS.map((t) => ({ label: TIER_LABEL[t], color: TIER_COLOR[t] }))} />
            </>
          )}
        </Card>
      </div>

      <div className="grid grid-3">
        <Card title="Deployed model" subtitle={model.data ? `${model.data.estimator ?? "—"} · version ${model.data.version}` : undefined}>
          {model.loading ? <Loading /> : model.error ? <ErrorState message={model.error} /> : model.data && (
            <>
              <div className="grid grid-2" style={{ gap: 10 }}>
                {MODEL_METRICS.map(([key, label]) => (
                  <div key={key} className="stat" style={{ gap: 2 }}>
                    <span className="stat-label">{label} · test</span>
                    <span style={{ fontSize: 20, fontWeight: 700 }}>{model.data!.offline_metrics.test?.[key]?.toFixed(3) ?? "—"}</span>
                  </div>
                ))}
                <div className="stat" style={{ gap: 2 }}>
                  <span className="stat-label">Features</span>
                  <span style={{ fontSize: 20, fontWeight: 700 }}>{model.data.n_raw_features} → {model.data.n_transformed_features ?? "—"}</span>
                </div>
              </div>
              <div className="divider" />
              <dl className="kv">
                <dt>Explanations</dt><dd>{health.data?.components.explainer.detail ?? "—"}</dd>
                <dt>Fairness post-processor</dt><dd>{health.data?.components.fairness_mitigator.loaded ? "Loaded" : "Unavailable"}</dd>
                <dt>Offline metrics</dt><dd>{MODEL_LABEL.xgb} · locked test split</dd>
              </dl>
            </>
          )}
        </Card>

        <Card title="Latest predictions" subtitle="Anonymous feed (no student identifiers are ever stored)" className="span-2"
          actions={<a className="btn btn-sm" href="#/monitoring">Open monitoring</a>}>
          {recent.loading ? <Loading /> : !recent.data || recent.data.items.length === 0 ? (
            <Empty title="Nothing scored yet" />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>When</th><th>Course</th><th className="r">Risk</th><th>Tier</th><th>Intervention</th><th>Top driver</th><th>Source</th></tr>
                </thead>
                <tbody>
                  {recent.data.items.map((item) => (
                    <tr key={item.prediction_id}>
                      <td className="muted nowrap">{timeAgo(item.timestamp)}</td>
                      <td className="mono">{item.code_module} {item.code_presentation}</td>
                      <td className="r num">{pct(item.risk_probability)}</td>
                      <td><TierBadge tier={item.risk_tier} /></td>
                      <td>{item.intervention_level}</td>
                      <td className="secondary">{item.top_driver ?? "—"}</td>
                      <td><span className="badge badge-neutral">{item.source}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
