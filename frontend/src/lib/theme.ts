import { createContext, useContext } from "react";
import type { RiskTier } from "./types";

export type ThemeName = "light" | "dark";

// Validated reference palette (dataviz skill): categorical slots 1-3 pass all-pairs CVD
// checks in both modes; tiers use the fixed status palette and always ship with icon + label.
const PALETTES = {
  light: {
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    grid: "#e1e0d9",
    axis: "#c3c2b7",
    text: "#52514e",
    textStrong: "#0b0b0b",
    muted: "#6f6e69",
    surface: "#fcfcfb",
    track: "#ebeae5",
    increase: "#e34948",
    decrease: "#2a78d6",
  },
  dark: {
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    grid: "#2c2c2a",
    axis: "#383835",
    text: "#c3c2b7",
    textStrong: "#f0efec",
    muted: "#9c9b95",
    surface: "#1a1a19",
    track: "#2c2c2a",
    increase: "#e66767",
    decrease: "#3987e5",
  },
} as const;

/** First-render size for ResponsiveContainer until ResizeObserver measures the real box. */
export const CHART_INIT = { width: 480, height: 240 };

export const STATUS = { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" } as const;

export const TIER_COLOR: Record<RiskTier, string> = {
  LOW: STATUS.good,
  MODERATE: STATUS.warning,
  HIGH: STATUS.serious,
  CRITICAL: STATUS.critical,
};

export const TIER_LABEL: Record<RiskTier, string> = {
  LOW: "Low",
  MODERATE: "Moderate",
  HIGH: "High",
  CRITICAL: "Critical",
};

export type ChartPalette = (typeof PALETTES)["light"] | (typeof PALETTES)["dark"];

export const ThemeContext = createContext<{ theme: ThemeName; toggle: () => void }>({
  theme: "light",
  toggle: () => undefined,
});

export function useChartPalette(): ChartPalette {
  const { theme } = useContext(ThemeContext);
  return PALETTES[theme];
}

export function tierForProbability(p: number, cuts: [number, number, number] = [0.2, 0.3, 0.5]): RiskTier {
  if (p < cuts[0]) return "LOW";
  if (p < cuts[1]) return "MODERATE";
  if (p < cuts[2]) return "HIGH";
  return "CRITICAL";
}
