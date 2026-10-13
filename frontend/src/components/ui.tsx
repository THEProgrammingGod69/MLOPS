import type { ReactNode } from "react";
import { AlertOctagon, AlertTriangle, CheckCircle2, CircleAlert, Inbox, Loader2, RefreshCw } from "lucide-react";
import type { RiskTier } from "../lib/types";
import { TIER_LABEL } from "../lib/theme";

export function Card(props: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`card ${props.flush ? "card-flush" : ""} ${props.className ?? ""}`}>
      {(props.title || props.actions) && (
        <header className="card-header">
          <div>
            {props.title && <h2 className="card-title">{props.title}</h2>}
            {props.subtitle && <div className="card-sub">{props.subtitle}</div>}
          </div>
          {props.actions && <div className="row-wrap">{props.actions}</div>}
        </header>
      )}
      {props.children}
    </section>
  );
}

export function StatTile(props: { label: string; value: ReactNode; foot?: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={`card stat ${props.className ?? ""}`}>
      <div className="spread">
        <span className="stat-label">{props.label}</span>
        {props.icon && <span className="stat-icon">{props.icon}</span>}
      </div>
      <div className="stat-value">{props.value}</div>
      {props.foot && <div className="stat-foot">{props.foot}</div>}
    </div>
  );
}

const TIER_ICON: Record<RiskTier, ReactNode> = {
  LOW: <CheckCircle2 size={13} aria-hidden />,
  MODERATE: <CircleAlert size={13} aria-hidden />,
  HIGH: <AlertTriangle size={13} aria-hidden />,
  CRITICAL: <AlertOctagon size={13} aria-hidden />,
};

export function TierBadge({ tier }: { tier: RiskTier }) {
  return (
    <span className={`badge tier-${tier}`}>
      {TIER_ICON[tier]}
      {TIER_LABEL[tier]}
    </span>
  );
}

export function StatusDot({ state }: { state: "good" | "bad" | "warn" }) {
  return <span className={`dot dot-${state}`} aria-hidden />;
}

export function Segmented<T extends string>(props: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={props.label}>
      {props.options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === props.value}
          onClick={() => props.onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <Loader2 size={16} className="spin" aria-hidden /> {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="callout callout-bad" role="alert">
      <AlertOctagon size={16} color="var(--critical)" aria-hidden />
      <div style={{ flex: 1 }}>
        <div className="error-box" style={{ fontWeight: 600 }}>Something went wrong</div>
        <div>{message}</div>
      </div>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          <RefreshCw size={13} aria-hidden /> Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon ?? <Inbox size={26} aria-hidden />}
      <div style={{ fontWeight: 600, color: "var(--text-secondary)" }}>{title}</div>
      {children && <div style={{ maxWidth: 420 }}>{children}</div>}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="legend">
      {items.map((item) => (
        <span key={item.label} className="legend-item">
          <span className="legend-swatch" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

interface TooltipEntry {
  name?: string | number;
  value?: number | string | (number | string)[];
  color?: string;
  payload?: Record<string, unknown>;
  dataKey?: string | number | ((obj: unknown) => unknown);
}

/** Recharts tooltip body in the app's design language. */
export function ChartTooltip(props: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
  format?: (value: number, name: string) => string;
  title?: (label: string | number | undefined, payload: TooltipEntry[]) => ReactNode;
}) {
  if (!props.active || !props.payload || props.payload.length === 0) return null;
  const format = props.format ?? ((v: number) => v.toFixed(3));
  return (
    <div className="tooltip">
      <div className="tooltip-title">{props.title ? props.title(props.label, props.payload) : props.label}</div>
      {props.payload.map((entry, i) => (
        <div className="tooltip-row" key={`${String(entry.name)}-${i}`}>
          <span className="row" style={{ gap: 6 }}>
            {entry.color && <span className="legend-swatch" style={{ background: entry.color }} />}
            {String(entry.name ?? "")}
          </span>
          <b>{typeof entry.value === "number" ? format(entry.value, String(entry.name)) : String(entry.value ?? "—")}</b>
        </div>
      ))}
    </div>
  );
}

export function InlineBar({ value, color, max = 1 }: { value: number; color: string; max?: number }) {
  const width = Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <span className="inline-bar" aria-hidden>
      <span style={{ width: `${width}%`, background: color }} />
    </span>
  );
}
