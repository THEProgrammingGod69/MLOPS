import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./lib/api";
import { duration, pct } from "./lib/format";
import { safeStorageGet, safeStorageSet, useApi, useHashRoute } from "./lib/hooks";
import { LedgerProvider, useLedger } from "./lib/ledger";
import { ThemeContext, type ThemeName } from "./lib/theme";
import type { Health, Meta } from "./lib/types";
import FrontPage from "./pages/FrontPage";
import AlertDesk from "./pages/AlertDesk";
import CaseFile from "./pages/CaseFile";
import Intake from "./pages/Intake";
import CohortLab from "./pages/CohortLab";
import TheModel from "./pages/TheModel";
import Monitoring from "./pages/Monitoring";

const PAGES: { path: string; label: string; element: () => ReactNode }[] = [
  { path: "/", label: "Front page", element: () => <FrontPage /> },
  { path: "/desk", label: "Alert desk", element: () => <AlertDesk /> },
  { path: "/case", label: "Case file", element: () => <CaseFile /> },
  { path: "/intake", label: "Intake", element: () => <Intake /> },
  { path: "/lab", label: "Cohort lab", element: () => <CohortLab /> },
  { path: "/model", label: "The model", element: () => <TheModel /> },
  { path: "/observatory", label: "Observatory", element: () => <Monitoring /> },
];

function initialTheme(): ThemeName {
  const stored = safeStorageGet("ew-theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function Waking() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <div className="waking" role="status">
      <div>
        <div className="kicker">Stop press</div>
        <h2>Warming the model.</h2>
        <p className="prose" style={{ margin: "0 auto" }}>This free deployment sleeps when nobody is reading. A fresh instance loads the model and an hour of monitoring history first. It takes about 15 seconds.</p>
        <div className="progress"><span style={{ width: `${Math.min(96, (seconds / 18) * 100)}%` }} /></div>
      </div>
    </div>
  );
}

function Ticker() {
  const { snapshot } = useLedger();
  const items = (snapshot?.open ?? []).slice(0, 14);
  if (!items.length) return null;
  const tape = items.map((c) => (
    <a key={c.id} href="#/desk">{c.ref} · {pct(c.risk_probability, 0)} · {c.top_driver ?? c.risk_tier}{c.origin === "simulator" ? " · demo" : ""}</a>
  ));
  return (
    <div className="ticker no-print" aria-label="Students at or above the alert threshold">
      <span className="tag">AT RISK</span>
      <div style={{ overflow: "hidden", flex: 1 }}><div className="tape" style={{ width: "max-content" }}>{tape}{tape.map((t, i) => <span key={i} aria-hidden>{t.props.children}</span>)}</div></div>
    </div>
  );
}

function Masthead({ health, meta, theme, toggle, route }: { health: Health | null; meta: Meta | null; theme: ThemeName; toggle: () => void; route: string }) {
  const { snapshot } = useLedger();
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const links = meta?.links;
  return (
    <header>
      <div className="dateline">
        <span>{today} · Day-28 edition</span>
        <div className="right">
          {health && <span>Model {health.model_version} · instance up {duration(health.uptime_seconds)}</span>}
          {links && <><a href={`${links.grafana}/d/mlops-monitoring`} target="_blank" rel="noreferrer">Grafana</a><a href={links.prometheus} target="_blank" rel="noreferrer">Prometheus</a><a href={links.api_docs} target="_blank" rel="noreferrer">API</a></>}
          <button className="linkbtn" onClick={toggle}>{theme === "dark" ? "Day edition" : "Night shift"}</button>
        </div>
      </div>
      <div className={`nameplate ${route === "/" ? "" : "compact"}`}>
        <a href="#/"><h1>The <em>Early</em> Warning</h1></a>
        <p className="motto">Which students are slipping at day 28, why, and what can still be done about it.</p>
      </div>
      <nav className="folio" aria-label="Sections">
        {PAGES.map((page, i) => (
          <a key={page.path} href={`#${page.path}`} className={page.path === route ? "active" : ""} aria-current={page.path === route ? "page" : undefined}>
            <span>{String(i + 1).padStart(2, "0")}</span>{page.label}
            {page.path === "/desk" && !!snapshot?.open_user_count && <b>{snapshot.open_user_count}</b>}
          </a>
        ))}
      </nav>
    </header>
  );
}

export default function App() {
  const route = useHashRoute();
  const [theme, setTheme] = useState<ThemeName>(initialTheme);
  const [ready, setReady] = useState(false);
  const health = useApi(api.ping, ready ? 10000 : 2000, [ready]);
  const meta = useApi(api.meta, 0, [ready]);

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);
  useEffect(() => { if (health.data?.status === "healthy") setReady(true); }, [health.data]);

  const themeValue = useMemo(() => ({
    theme,
    toggle: () => setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      safeStorageSet("ew-theme", next);
      return next;
    }),
  }), [theme]);

  const active = PAGES.find((p) => p.path === route) ?? PAGES[0];

  return (
    <ThemeContext.Provider value={themeValue}>
      <LedgerProvider instance={health.data?.instance_started_at}>
        <div className="paper">
          <Masthead health={health.data} meta={meta.data} theme={theme} toggle={themeValue.toggle} route={active.path} />
          <Ticker />
          <main className="main" id="content">{ready ? active.element() : <Waking />}</main>
          <footer className="colophon no-print">
            <span>Predictions support advisors and never decide alone. Public demo: the model is trained on synthetic data shaped like OULAD.</span>
            <span>XGBoost · SHAP · fairlearn · FastAPI · Prometheus · Grafana</span>
          </footer>
        </div>
      </LedgerProvider>
    </ThemeContext.Provider>
  );
}
