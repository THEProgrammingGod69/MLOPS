import { TIER_COLOR, tierForProbability, useChartPalette } from "../lib/theme";
import type { RiskTier } from "../lib/types";

/**
 * Semicircular risk meter. The track is split at the configured tier boundaries
 * (status colours), and the needle marks the predicted probability.
 */
export function RiskGauge({ probability, cuts = [0.2, 0.3, 0.5] }: { probability: number; cuts?: [number, number, number] }) {
  const palette = useChartPalette();
  const size = 210;
  const stroke = 16;
  const r = (size - stroke) / 2 - 4;
  const cx = size / 2;
  const cy = size / 2 + 6;
  const angle = (p: number) => Math.PI * (1 - p); // 0 -> left, 1 -> right
  const point = (p: number, radius = r) => [cx + radius * Math.cos(angle(p)), cy - radius * Math.sin(angle(p))];
  const arc = (from: number, to: number) => {
    const [x1, y1] = point(from);
    const [x2, y2] = point(to);
    return `M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`;
  };
  const bounds: [number, number, RiskTier][] = [
    [0, cuts[0], "LOW"],
    [cuts[0], cuts[1], "MODERATE"],
    [cuts[1], cuts[2], "HIGH"],
    [cuts[2], 1, "CRITICAL"],
  ];
  const gap = 0.006;
  const p = Math.max(0, Math.min(1, probability));
  const [nx, ny] = point(p, r - stroke / 2 - 6);
  const tier = tierForProbability(p, cuts);

  return (
    <svg width={size} height={size / 2 + 36} viewBox={`0 0 ${size} ${size / 2 + 36}`} role="img"
      aria-label={`Predicted dropout probability ${(p * 100).toFixed(1)} percent, ${tier.toLowerCase()} risk`}>
      <path d={arc(0, 1)} stroke={palette.track} strokeWidth={stroke} fill="none" strokeLinecap="round" />
      {bounds.map(([from, to, t]) => (
        <path key={t} d={arc(from + (from > 0 ? gap : 0), to - (to < 1 ? gap : 0))} stroke={TIER_COLOR[t]}
          strokeOpacity={t === tier ? 1 : 0.28} strokeWidth={stroke} fill="none"
          strokeLinecap={from === 0 || to === 1 ? "round" : "butt"} />
      ))}
      <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={palette.textStrong} strokeWidth={2.5} strokeLinecap="round" />
      <circle cx={cx} cy={cy} r={6} fill={palette.textStrong} />
      <circle cx={cx} cy={cy} r={2.5} fill={palette.surface} />
      <text x={cx - r} y={cy + stroke + 17} fontSize={11} fill={palette.muted} textAnchor="middle">0%</text>
      <text x={cx + r} y={cy + stroke + 17} fontSize={11} fill={palette.muted} textAnchor="middle">100%</text>
    </svg>
  );
}
