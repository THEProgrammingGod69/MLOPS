import { useMemo, useState } from "react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Info } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { int, MODEL_LABEL, num, pct, titleCase } from "../lib/format";
import { useApi } from "../lib/hooks";
import { CHART_INIT, useChartPalette } from "../lib/theme";
import type { Row } from "../lib/types";
import { Card, ChartTooltip, Empty, ErrorState, InlineBar, Legend, Loading, Segmented } from "../components/ui";

const ATTRIBUTES = ["gender", "disability", "age_band", "region", "imd_band"] as const;
type Attribute = (typeof ATTRIBUTES)[number];
const ATTRIBUTE_LABEL: Record<Attribute, string> = {
  gender: "Gender", disability: "Disability", age_band: "Age band", region: "Region", imd_band: "IMD band",
};
const METHODS = ["ThresholdOptimizer", "ExponentiatedGradient"];
const SMALL_GROUP = 50;

export default function Fairness() {
  const palette = useChartPalette();
  const fairness = useApi(api.insightsFairness);
  const models = useApi(api.insightsModels);
  const [model, setModel] = useState<"lr" | "rf" | "xgb">("xgb");
  const [split, setSplit] = useState<"validation" | "test">("test");
  const [attribute, setAttribute] = useState<Attribute>("region");

  const disparity = useMemo(() => {
    const rows = (fairness.data?.disparity ?? []).filter((r) => r.model === model && r.split === split);
    return ATTRIBUTES.map((a) => {
      const r = rows.find((x) => x.sensitive_attribute === a);
      return {
        attribute: ATTRIBUTE_LABEL[a],
        dpd: r ? Number(r.demographic_parity_difference) : null,
        eod: r ? Number(r.equalized_odds_difference) : null,
        minGroup: r ? Number(r.min_group_count) : null,
        groups: r ? Number(r.n_groups) : null,
      };
    });
  }, [fairness.data, model, split]);

  const groups = useMemo(
    () => (fairness.data?.groups ?? [])
      .filter((r) => r.model === model && r.split === split && r.sensitive_attribute === attribute)
      .sort((a, b) => Number(b.true_positive_rate) - Number(a.true_positive_rate)),
    [fairness.data, model, split, attribute],
  );

  // Deployed mitigation: XGBoost + ThresholdOptimizer (equalized odds) on gender, evaluated once on test.
  const mitigated = (fairness.data?.mitigation ?? []).find((r) => r.split === "test" && r.model === "xgb" && r.sensitive_attribute === "gender");
  const baseFair = (fairness.data?.disparity ?? []).find((r) => r.split === "test" && r.model === "xgb" && r.sensitive_attribute === "gender");
  const baseMetric = (metric: string) => models.data?.comparison.find((r) => r.model === "xgb" && r.split === "test" && r.metric === metric)?.value ?? null;
  const mitigationRows: { label: string; base: number | null; after: number | null; better: "lower" | "higher" }[] = mitigated ? [
    { label: "Demographic parity difference", base: baseFair ? Number(baseFair.demographic_parity_difference) : null, after: Number(mitigated.demographic_parity_difference), better: "lower" },
    { label: "Equalized odds difference", base: baseFair ? Number(baseFair.equalized_odds_difference) : null, after: Number(mitigated.equalized_odds_difference), better: "lower" },
    { label: "Recall (withdrawals caught)", base: baseMetric("recall"), after: Number(mitigated.recall), better: "higher" },
    { label: "Precision", base: baseMetric("precision"), after: Number(mitigated.precision), better: "higher" },
    { label: "F1", base: baseMetric("f1"), after: Number(mitigated.f1), better: "higher" },
    { label: "Accuracy", base: baseMetric("accuracy"), after: Number(mitigated.accuracy), better: "higher" },
  ] : [];

  const explored = useMemo(() => {
    const rows = (fairness.data?.mitigation ?? []).filter((r) => r.split === "validation" && r.model === "xgb");
    return ATTRIBUTES.map((a) => {
      const entry: Record<string, string | number> = { attribute: ATTRIBUTE_LABEL[a] };
      for (const m of METHODS) {
        const best = rows.filter((r) => r.sensitive_attribute === a && r.mitigation_method === m)
          .map((r) => Number(r.equalized_odds_difference));
        if (best.length) entry[m] = Math.min(...best);
      }
      const base = (fairness.data?.disparity ?? []).find((r) => r.model === "xgb" && r.split === "validation" && r.sensitive_attribute === a);
      if (base) entry.Baseline = Number(base.equalized_odds_difference);
      return entry;
    });
  }, [fairness.data]);

  if (fairness.loading) return <Loading />;
  if (fairness.error) return <ErrorState message={fairness.error} onRetry={fairness.reload} />;

  const smallGroups = groups.filter((g) => Number(g.group_count) < SMALL_GROUP);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Fairness</h1>
          <p className="page-desc">
            Audit of how evenly the model's alerts fall across protected groups. Sensitive attributes are never model
            inputs; they are used only to measure disparities and, for gender, by the post-processing step.
          </p>
        </div>
        <div className="page-actions">
          <Segmented label="Model" value={model} onChange={setModel}
            options={[{ value: "lr", label: "LR" }, { value: "rf", label: "RF" }, { value: "xgb", label: "XGBoost" }]} />
          <Segmented label="Split" value={split} onChange={setSplit}
            options={[{ value: "validation", label: "Validation" }, { value: "test", label: "Test" }]} />
        </div>
      </div>

      <div className="grid grid-2 mb-16">
        <Card title="Disparity by attribute" subtitle={`${MODEL_LABEL[model]}, ${split} split, decision threshold 0.5. Closer to 0 is fairer`}>
          <div className="chart" style={{ height: 260 }}>
            <ResponsiveContainer initialDimension={CHART_INIT}>
              <BarChart data={disparity} margin={{ top: 8, right: 8, left: -14, bottom: 0 }} barGap={2}>
                <CartesianGrid vertical={false} stroke={palette.grid} />
                <XAxis dataKey="attribute" tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: palette.muted }} />
                <ReferenceLine y={0.1} stroke={palette.muted} strokeDasharray="4 4"
                  label={{ value: "0.10 review line", position: "insideTopLeft", fill: palette.muted, fontSize: 11 }} />
                <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }}
                  content={<ChartTooltip title={(l, p) => `${l} · smallest group n=${int(Number(p[0]?.payload?.minGroup))}`} />} />
                <Bar dataKey="dpd" name="Demographic parity diff." fill={palette.series[0]} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                <Bar dataKey="eod" name="Equalized odds diff." fill={palette.series[1]} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <Legend items={[{ label: "Demographic parity difference", color: palette.series[0] }, { label: "Equalized odds difference", color: palette.series[1] }]} />
        </Card>

        <Card title="Deployed mitigation: before and after" subtitle="XGBoost + ThresholdOptimizer (equalized odds) on gender, locked test split">
          {mitigationRows.length === 0 ? <Empty title="No mitigation report" /> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Metric</th><th className="r">Baseline</th><th className="r">Mitigated</th><th className="r">Change</th></tr></thead>
                <tbody>
                  {mitigationRows.map((r) => {
                    const delta = r.base !== null && r.after !== null ? r.after - r.base : null;
                    const improved = delta !== null && (r.better === "lower" ? delta < 0 : delta > 0);
                    return (
                      <tr key={r.label}>
                        <td>{r.label}</td>
                        <td className="r num">{num(r.base)}</td>
                        <td className="r num"><strong>{num(r.after)}</strong></td>
                        <td className="r num" style={{ color: delta === null || Math.abs(delta) < 1e-9 ? "var(--text-muted)" : improved ? "var(--good-text)" : "var(--critical-text)" }}>
                          {delta === null ? "—" : (
                            <span className="row" style={{ justifyContent: "flex-end", gap: 3 }}>
                              {delta > 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{delta > 0 ? "+" : ""}{delta.toFixed(3)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="callout mt-16"><Info size={15} />
            <span>Green marks movement in the desirable direction. The post-processor trades a little precision for
              catching more withdrawals while equalising error rates between groups.</span>
          </div>
        </Card>
      </div>

      <Card title="Group-level outcomes" className="mb-16"
        subtitle={`${MODEL_LABEL[model]}, ${split} split. Selection rate = share flagged; TPR = withdrawals caught; FPR = false alarms`}
        actions={<Segmented label="Attribute" value={attribute} onChange={setAttribute}
          options={ATTRIBUTES.map((a) => ({ value: a, label: ATTRIBUTE_LABEL[a] }))} />}>
        {groups.length === 0 ? <Empty title="No group metrics for this selection" /> : (
          <>
            {smallGroups.length > 0 && (
              <div className="callout callout-warn mb-16"><AlertTriangle size={15} color="var(--warning)" />
                <span>{smallGroups.map((g) => `${g.group} (n=${g.group_count})`).join(", ")} {smallGroups.length === 1 ? "is" : "are"} below {SMALL_GROUP} students; treat {smallGroups.length === 1 ? "its" : "their"} rates as noisy.</span>
              </div>
            )}
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Group</th><th className="r">Students</th><th className="r">Withdrawn</th><th>Selection rate</th><th>True positive rate</th><th>False positive rate</th><th className="r">Precision</th></tr>
                </thead>
                <tbody>
                  {groups.map((g: Row) => (
                    <tr key={String(g.group)}>
                      <td>{String(g.group)}</td>
                      <td className="r num">{int(Number(g.group_count))}</td>
                      <td className="r num">{int(Number(g.positive_count))}</td>
                      <td><span className="row"><InlineBar value={Number(g.selection_rate)} max={0.25} color={palette.series[0]} /><span className="num">{pct(Number(g.selection_rate))}</span></span></td>
                      <td><span className="row"><InlineBar value={Number(g.true_positive_rate)} max={0.5} color={palette.series[2]} /><span className="num">{pct(Number(g.true_positive_rate))}</span></span></td>
                      <td><span className="row"><InlineBar value={Number(g.false_positive_rate)} max={0.1} color={palette.series[1]} /><span className="num">{pct(Number(g.false_positive_rate))}</span></span></td>
                      <td className="r num">{g.precision === null ? "—" : pct(Number(g.precision))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>

      <Card title="Mitigation exploration" subtitle="Best equalized odds difference per method on validation (XGBoost); lower is fairer">
        <div className="chart" style={{ height: 260 }}>
          <ResponsiveContainer initialDimension={CHART_INIT}>
            <BarChart data={explored} margin={{ top: 8, right: 8, left: -14, bottom: 0 }} barGap={2}>
              <CartesianGrid vertical={false} stroke={palette.grid} />
              <XAxis dataKey="attribute" tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: palette.muted }} />
              <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }} content={<ChartTooltip />} />
              <Bar dataKey="Baseline" name="Baseline" fill={palette.series[0]} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
              {METHODS.map((m, i) => (
                <Bar key={m} dataKey={m} name={titleCase(m.replace(/([a-z])([A-Z])/g, "$1 $2"))} fill={palette.series[i + 1]} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <Legend items={[{ label: "Baseline", color: palette.series[0] }, { label: "Threshold Optimizer", color: palette.series[1] }, { label: "Exponentiated Gradient", color: palette.series[2] }]} />
      </Card>
    </>
  );
}
