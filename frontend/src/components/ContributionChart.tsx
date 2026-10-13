import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Contribution, FeatureValue } from "../lib/types";
import { CHART_INIT, useChartPalette } from "../lib/theme";
import { ChartTooltip, Legend } from "./ui";

const formatValue = (value: FeatureValue): string => {
  if (value === null) return "missing";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(1);
  return value;
};

/**
 * Diverging bar chart of per-feature SHAP contributions (log-odds). Red pushes the
 * dropout risk up, blue pulls it down; the y-axis carries each feature's input value.
 */
export function ContributionChart({ contributions, limit = 10 }: { contributions: Contribution[]; limit?: number }) {
  const palette = useChartPalette();
  const data = contributions
    .filter((c) => Math.abs(c.contribution) > 1e-6)
    .slice(0, limit)
    .map((c) => ({ ...c, name: `${c.label} · ${formatValue(c.value)}` }));
  const raw = Math.max(0.05, ...data.map((d) => Math.abs(d.contribution)));
  const step = [0.05, 0.1, 0.25, 0.5, 1, 2, 5].find((s) => raw / s <= 2) ?? 10;
  const extent = Math.ceil(raw / step) * step;
  const ticks = [-extent, -extent / 2, 0, extent / 2, extent];
  const height = 34 * data.length + 46;

  return (
    <div>
      <div className="chart" style={{ height }}>
        <ResponsiveContainer initialDimension={CHART_INIT}>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 4 }} barCategoryGap={6}>
            <CartesianGrid horizontal={false} stroke={palette.grid} />
            <XAxis type="number" domain={[-extent, extent]} ticks={ticks} tickFormatter={(v: number) => (v === 0 ? "0" : v.toFixed(2))}
              stroke={palette.axis} tick={{ fill: palette.muted }} tickLine={false} />
            <YAxis type="category" dataKey="name" width={230} tickLine={false} axisLine={false}
              tick={{ fill: palette.text, fontSize: 12 }} interval={0}
              tickFormatter={(v: string) => (v.length > 34 ? `${v.slice(0, 33)}…` : v)} />
            <ReferenceLine x={0} stroke={palette.axis} />
            <Tooltip cursor={{ fill: palette.track, opacity: 0.5 }}
              content={<ChartTooltip format={(v) => `${v > 0 ? "+" : ""}${v.toFixed(3)} log-odds`}
                title={(_, payload) => String(payload[0]?.payload?.name ?? "")} />} />
            <Bar dataKey="contribution" name="Contribution" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.feature} fill={d.contribution > 0 ? palette.increase : palette.decrease} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[{ label: "Raises dropout risk", color: palette.increase }, { label: "Lowers dropout risk", color: palette.decrease }]} />
    </div>
  );
}
