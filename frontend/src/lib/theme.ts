import { createContext, useContext } from "react";
import type { RiskTier } from "./types";

export type ThemeName = "light" | "dark";

// Validated reference palette (dataviz skill): categorical slots 1-3 pass all-pairs CVD
// checks in both modes; tiers use the fixed status palette and always ship with icon + label.
const PALETTES = {
  light: {
    series: ["#22408c", "#c8321c", "#3f6b4a", "#b8801f", "#7d3f77", "#16130f", "#3d8c95", "#8a6d3b"],
    grid: "#d9d0bc",
    axis: "#a89e88",
    text: "#4a443a",
    textStrong: "#16130f",
    muted: "#6d6555",
    surface: "#f4efe4",
    track: "#ded5c1",
    increase: "#c8321c",
    decrease: "#22408c",
  },
  dark: {
    series: ["#8ba6ec", "#f0593b", "#79ad87", "#d9a441", "#c98cc2", "#efe8d8", "#6dbdc6", "#c4a875"],
    grid: "#2f2a21",
    axis: "#554d3f",
    text: "#c4bba8",
    textStrong: "#efe8d8",
    muted: "#978e7b",
    surface: "#14110d",
    track: "#2b261e",
    increase: "#f0593b",
    decrease: "#8ba6ec",
  },
} as const;

/** First-render size for ResponsiveContainer until ResizeObserver measures the real box. */
export const CHART_INIT = { width: 480, height: 240 };

export const STATUS = { good: "#3f6b4a", warning: "#b8801f", serious: "#d2622a", critical: "#c8321c" } as const;

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
