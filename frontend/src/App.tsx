import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity, BarChart3, BookOpen, Gauge, LayoutDashboard, Menu, Moon, Scale, ShieldCheck, Sun, Upload, UserSearch, X,
} from "lucide-react";
import { api } from "./lib/api";
import { safeStorageGet, safeStorageSet, useApi, useHashRoute } from "./lib/hooks";
import { ThemeContext, type ThemeName } from "./lib/theme";
import { StatusDot } from "./components/ui";
import Overview from "./pages/Overview";
import Assess from "./pages/Assess";
import Batch from "./pages/Batch";
import Insights from "./pages/Insights";
import Fairness from "./pages/Fairness";
import Monitoring from "./pages/Monitoring";

interface NavEntry {
  path: string;
  label: string;
  icon: ReactNode;
  element: () => ReactNode;
}

const NAV: { section: string; items: NavEntry[] }[] = [
  {
    section: "Advise",
    items: [
      { path: "/", label: "Overview", icon: <LayoutDashboard size={17} />, element: () => <Overview /> },
      { path: "/assess", label: "Risk assessment", icon: <UserSearch size={17} />, element: () => <Assess /> },
      { path: "/batch", label: "Batch scoring", icon: <Upload size={17} />, element: () => <Batch /> },
    ],
  },
  {
    section: "Govern",
    items: [
      { path: "/insights", label: "Model insights", icon: <BarChart3 size={17} />, element: () => <Insights /> },
      { path: "/fairness", label: "Fairness", icon: <Scale size={17} />, element: () => <Fairness /> },
      { path: "/monitoring", label: "Live monitoring", icon: <Activity size={17} />, element: () => <Monitoring /> },
    ],
  },
];

function initialTheme(): ThemeName {
  const stored = safeStorageGet("ew-theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const route = useHashRoute();
  const [theme, setTheme] = useState<ThemeName>(initialTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const health = useApi(api.health, 10000);
  const meta = useApi(api.meta);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  useEffect(() => setMenuOpen(false), [route]);

  const themeValue = useMemo(
    () => ({
      theme,
      toggle: () =>
        setTheme((current) => {
          const next = current === "dark" ? "light" : "dark";
          safeStorageSet("ew-theme", next);
          return next;
        }),
    }),
    [theme],
  );

  const entries = NAV.flatMap((s) => s.items);
  const active = entries.find((e) => e.path === route) ?? entries[0];
  const healthy = health.data?.status === "healthy";
  const statusText = health.error ? "API unreachable" : health.data ? (healthy ? "Service healthy" : "Model not loaded") : "Checking…";
  const links = meta.data?.links;

  const sidebar = (
    <nav className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Main">
      <div className="brand">
        <div className="brand-mark"><ShieldCheck size={19} aria-hidden /></div>
        <div>
          <div className="brand-name">EarlyWarning</div>
          <div className="brand-sub">Student success · MLOps</div>
        </div>
      </div>
      {NAV.map((section) => (
        <div key={section.section}>
          <div className="nav-label">{section.section}</div>
          {section.items.map((item) => (
            <a key={item.path} href={`#${item.path}`} className={`nav-item ${item === active ? "active" : ""}`}
              aria-current={item === active ? "page" : undefined}>
              {item.icon}
              {item.label}
            </a>
          ))}
        </div>
      ))}
      <div className="sidebar-footer">
        <div className="row" style={{ fontSize: 12.5 }}>
          <StatusDot state={health.error ? "bad" : healthy ? "good" : "warn"} />
          <span style={{ fontWeight: 600 }}>{statusText}</span>
        </div>
        {health.data && (
          <div className="muted" style={{ fontSize: 11.5 }}>
            Model <span className="mono">{health.data.model_version}</span> · API v{health.data.version}
          </div>
        )}
        <div className="sidebar-links">
          {links && (
            <>
              <a className="btn btn-sm" href={links.grafana} target="_blank" rel="noreferrer"><Gauge size={13} /> Grafana</a>
              <a className="btn btn-sm" href={links.prometheus} target="_blank" rel="noreferrer"><Activity size={13} /> Prometheus</a>
              <a className="btn btn-sm" href={links.api_docs} target="_blank" rel="noreferrer"><BookOpen size={13} /> API docs</a>
            </>
          )}
        </div>
        <button className="btn btn-sm btn-ghost" onClick={themeValue.toggle} style={{ justifyContent: "flex-start" }}>
          {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />} {theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
      </div>
    </nav>
  );

  return (
    <ThemeContext.Provider value={themeValue}>
      <div className="shell">
        <div className="sidebar-col">{sidebar}</div>
        {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} />}
        <div>
          <header className="topbar">
            <div className="row">
              <div className="brand-mark" style={{ width: 28, height: 28 }}><ShieldCheck size={16} /></div>
              <strong>EarlyWarning</strong>
            </div>
            <div className="row">
              <StatusDot state={health.error ? "bad" : healthy ? "good" : "warn"} />
              <button className="btn btn-icon btn-ghost" aria-label="Open menu" onClick={() => setMenuOpen((o) => !o)}>
                {menuOpen ? <X size={18} /> : <Menu size={18} />}
              </button>
            </div>
          </header>
          <main className="main" id="content">
            {active.element()}
          </main>
        </div>
      </div>
    </ThemeContext.Provider>
  );
}
