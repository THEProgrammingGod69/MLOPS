import { useRef, useState, type DragEvent } from "react";
import { Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { int, pct } from "../lib/format";
import { safeStorageGet, safeStorageSet } from "../lib/hooks";
import { useLedger } from "../lib/ledger";
import type { AdapterResult, Inspection, Mapping } from "../lib/types";
import { ErrorState, TierBadge } from "../components/ui";

const SAMPLES = [
  { file: "sample-engineering-college.csv", label: "Engineering college", note: "CGPA /10, attendance %, Moodle logins" },
  { file: "sample-community-college.csv", label: "Community college", note: "GPA /4, Canvas views, credit hours" },
  { file: "sample-secondary-school.csv", label: "Secondary school", note: "Letter grades, absences, semicolons" },
];
const TRANSFORM_LABEL: Record<string, string> = {
  as_is: "Use as is", percentile: "Percentile match", score_100: "Rescale to 100", days_since_date: "Days since date", days_from_start: "Days from start",
  weeks_to_days: "Weeks → days", months_to_days: "Months → days", education: "Map levels", module: "Map courses", presentation: "Map terms",
};
const ROLE_LABEL: Record<string, string> = { student_id: "Student ID", gender: "Gender", outcome: "Known outcome", course_start: "Course start date", as_of: "Snapshot date" };
const PROFILES_KEY = "ew-profiles-v1";
const ORIGIN_COLOR: Record<string, string> = { direct: "var(--good)", derived: "var(--good)", scaled: "var(--good)", proxy: "var(--warning)", rule: "var(--warning)", latent: "var(--axis)", native_missing: "var(--surface-3)", default: "var(--surface-3)" };

const signature = (columns: string[]) => [...columns].sort().join("|").toLowerCase();
function savedProfiles(): Record<string, Mapping> {
  try { return JSON.parse(safeStorageGet(PROFILES_KEY) ?? "{}"); } catch { return {}; }
}

function download(result: AdapterResult) {
  const rows = [["reference", "risk_probability", "risk_tier", "cohort_percentile", "intervention", "top_driver"],
    ...result.rows.map((r) => [r.reference, r.risk_probability.toFixed(4), r.risk_tier, String(r.cohort_percentile), r.intervention_level, r.top_driver ?? ""])];
  const csv = rows.map((row) => row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${result.cohort.replace(/\W+/g, "-")}-risk.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Intake() {
  const { setCohort } = useLedger();
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [recognised, setRecognised] = useState(false);
  const [cohortName, setCohortName] = useState("");
  const [result, setResult] = useState<AdapterResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [saved, setSaved] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function open(next: File) {
    setError(null); setResult(null); setBusy(true); setSaved(false);
    try {
      const report = await api.inspect(next);
      setFile(next);
      setInspection(report);
      const stored = savedProfiles()[signature(report.columns.map((c) => c.name))];
      setMapping(stored ?? report.proposal);
      setRecognised(Boolean(stored));
      setCohortName(next.name.replace(/\.[^.]+$/, "").replace(/^sample-/, "").replace(/-/g, " "));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function sample(name: string) {
    setBusy(true);
    try {
      const response = await fetch(`samples/${name}`);
      await open(new File([await response.blob()], name, { type: "text/csv" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); setBusy(false);
    }
  }

  async function run() {
    if (!file || !mapping) return;
    setError(null); setBusy(true);
    try {
      const scored = await api.scoreUpload(file, mapping, cohortName || "uploaded cohort");
      setResult(scored);
      setCohort(scored);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  function setColumn(feature: string, column: string) {
    const target = inspection!.targets.find((t) => t.feature === feature)!;
    setMapping((m) => ({ ...m!, targets: { ...m!.targets, [feature]: { column: column || null, confidence: column ? 1 : 0, origin: "direct", transform: column ? (m!.targets[feature]?.transform ?? target.transforms[0]) : null } } }));
    setResult(null);
  }
  const setTransform = (feature: string, transform: string) => { setMapping((m) => ({ ...m!, targets: { ...m!.targets, [feature]: { ...m!.targets[feature], transform } } })); setResult(null); };
  const setRole = (role: string, column: string) => { setMapping((m) => ({ ...m!, roles: { ...m!.roles, [role]: column || null } })); setResult(null); };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); const dropped = e.dataTransfer.files[0]; if (dropped) void open(dropped); };

  const stage = result ? 3 : inspection ? 2 : 1;
  const mapped = mapping ? Object.values(mapping.targets).filter((t) => t.column).length : 0;

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Intake</h1>
          <p className="page-desc">Every institution keeps records differently. Bring yours in any shape: the adapter works out which columns mean what, converts the units, and tells you honestly how far the result can be trusted.</p>
        </div>
      </div>
      <div className="steps">{["1 · Bring a file", "2 · Check the mapping", "3 · Read the verdict"].map((s, i) => <span key={s} className={stage === i + 1 ? "on" : ""}>{s}</span>)}</div>
      {error && <div className="mb-16"><ErrorState message={error} /></div>}

      {stage === 1 && (
        <div className="split">
          <div className={`dropzone ${over ? "over" : ""}`} role="button" tabIndex={0} onClick={() => input.current?.click()} onKeyDown={(e) => { if (e.key === "Enter") input.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
            <input ref={input} type="file" hidden accept=".csv,.tsv,.txt,.xlsx,.xlsm,.json" onChange={(e) => { const f = e.target.files?.[0]; if (f) void open(f); }} />
            <div className="display" style={{ fontSize: 34 }}>{busy ? "Reading…" : "Drop a file here"}</div>
            <p className="muted" style={{ marginBottom: 0 }}>CSV, TSV, Excel or JSON, up to 4 MB and 2,000 students. Any column names, grading scale or date format.</p>
          </div>
          <div>
            <div className="kicker" style={{ color: "var(--text-secondary)" }}>Or try a stranger’s records</div>
            <div className="mt-8">
              {SAMPLES.map((s) => (
                <div key={s.file} className="spread" style={{ padding: "11px 0", borderBottom: "1px solid var(--border)" }}>
                  <div><div style={{ fontWeight: 650 }}>{s.label}</div><div className="muted" style={{ fontSize: 13.5 }}>{s.note}</div></div>
                  <button className="btn btn-sm" disabled={busy} onClick={() => void sample(s.file)}>Open</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {inspection && mapping && !result && (
        <>
          <div className="spread mb-16" style={{ flexWrap: "wrap" }}>
            <p className="prose" style={{ margin: 0, fontSize: 16 }}><strong>{inspection.filename}</strong>: {int(inspection.rows)} students, {inspection.columns.length} columns. {mapped} of 21 model inputs matched automatically{recognised ? ", using your saved format" : ""}. Anything unmatched is inferred or left neutral, and the verdict will say so.</p>
            <div className="row-wrap">
              <button className="btn" onClick={() => { setInspection(null); setMapping(null); setFile(null); }}>Start over</button>
              <button className="btn" onClick={() => { safeStorageSet(PROFILES_KEY, JSON.stringify({ ...savedProfiles(), [signature(inspection.columns.map((c) => c.name))]: mapping })); setSaved(true); }}>{saved ? "Format saved" : "Remember this format"}</button>
              <button className="btn btn-primary" disabled={busy} onClick={() => void run()}>{busy && <Loader2 size={15} className="spin" />}Score {int(Math.min(inspection.rows, 2000))} students</button>
            </div>
          </div>
          {inspection.rows > 2000 && <div className="callout callout-warn mb-16">Only the first 2,000 rows will be scored.</div>}

          <div className="split" style={{ gridTemplateColumns: "minmax(0, 2.2fr) minmax(0, 1fr)" }}>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Model input</th><th>Your column</th><th>Conversion</th><th>Match</th></tr></thead>
                <tbody>
                  {inspection.targets.map((t) => {
                    const a = mapping.targets[t.feature];
                    return (
                      <tr key={t.feature}>
                        <td style={{ fontWeight: 600 }}>{t.label}</td>
                        <td><select aria-label={`Column for ${t.label}`} className="select" value={a?.column ?? ""} onChange={(e) => setColumn(t.feature, e.target.value)}><option value="">Not recorded</option>{inspection.columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></td>
                        <td>{a?.column ? <select aria-label={`Conversion for ${t.label}`} className="select" value={a.transform ?? ""} onChange={(e) => setTransform(t.feature, e.target.value)}>{t.transforms.map((v) => <option key={v} value={v}>{TRANSFORM_LABEL[v] ?? v}</option>)}</select> : <span className="muted">Inferred or neutral</span>}</td>
                        <td>{a?.column ? <div className="confidence" title={pct(a.confidence, 0)}><span style={{ width: `${a.confidence * 100}%` }} /></div> : null}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <aside className="stack">
              <section className="card">
                <header className="card-header"><h2 className="card-title">Special columns</h2></header>
                <div className="stack" style={{ gap: 14 }}>
                  {Object.keys(ROLE_LABEL).map((role) => (
                    <div className="field" key={role}><label className="field-label" htmlFor={`r-${role}`}>{ROLE_LABEL[role]}</label><select id={`r-${role}`} className="select" value={mapping.roles[role] ?? ""} onChange={(e) => setRole(role, e.target.value)}><option value="">None</option>{inspection.columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></div>
                  ))}
                  <div className="field"><label className="field-label" htmlFor="cohort-name">Cohort name</label><input id="cohort-name" className="input" value={cohortName} onChange={(e) => setCohortName(e.target.value)} maxLength={40} /></div>
                </div>
              </section>
              <p className="muted" style={{ fontSize: 13.5, margin: 0 }}>Add a known-outcome column and the adapter tests the model on your real results and recalibrates it.</p>
            </aside>
          </div>
        </>
      )}

      {result && (
        <div className="stack">
          <div className="front">
            <article>
              <div className="kicker">Institution fit</div>
              <div className="big-number">{Math.round(result.fit.score)}<small>/100</small></div>
              <p className="brief">{result.fit.advice}</p>
              <div className="fitbar" role="img" aria-label="How the 21 inputs were obtained">
                {Object.entries(result.fit.origin_counts).map(([origin, n]) => <span key={origin} title={`${origin}: ${n}`} style={{ flex: n, background: ORIGIN_COLOR[origin], marginRight: 2 }} />)}
              </div>
            </article>
            <section>
              <div className="kicker" style={{ color: "var(--text-secondary)" }}>Scored</div>
              <div className="stat-value">{int(result.count)}</div>
              <ul className="leaders mt-8">
                {(["CRITICAL", "HIGH", "MODERATE", "LOW"] as const).map((t) => <li key={t}><span><TierBadge tier={t} /></span><b>{int(result.tier_counts[t])}</b></li>)}
              </ul>
              <p className="alert-slip mt-16" style={{ marginBottom: 0 }}><strong>{int(result.alerts_opened)} alerts raised</strong> at {pct(result.alert_threshold, 0)} or above. <a href="#/desk">Open the desk</a></p>
            </section>
            <aside>
              <div className="kicker" style={{ color: "var(--text-secondary)" }}>Tested on your outcomes</div>
              {result.validation.available ? (
                <>
                  <div className="stat-value">{result.validation.auc?.toFixed(2)}</div>
                  <div className="stat-foot">AUC on {int(result.validation.n)} students whose outcome you recorded</div>
                  <ul className="leaders mt-8">
                    <li><span>Dropout rate here</span><b>{pct(result.validation.base_rate)}</b></li>
                    <li><span>Brier, raw</span><b>{result.validation.brier_raw?.toFixed(3)}</b></li>
                    <li><span>Brier, recalibrated</span><b>{result.validation.brier_calibrated?.toFixed(3)}</b></li>
                  </ul>
                  <p className="muted" style={{ fontSize: 13 }}>Probabilities below use the recalibration fitted to this file.</p>
                </>
              ) : <p className="muted">{result.validation.reason} Without one, nobody can say how accurate this is for your students. Use the ranking first.</p>}
            </aside>
          </div>

          <div className="row-wrap no-print">
            <a className="btn btn-primary" href="#/lab">Plan the response in the cohort lab</a>
            <button className="btn" onClick={() => download(result)}>Download results</button>
            <button className="btn" onClick={() => setResult(null)}>Change the mapping</button>
          </div>
          {result.truncated_rows > 0 && <div className="callout callout-warn">{int(result.truncated_rows)} rows beyond the 2,000 limit were not scored.</div>}

          <section className="card">
            <header className="card-header"><div><h2 className="card-title">Highest risk first</h2><div className="card-sub">Cohort rank stays meaningful even when the fit is low.</div></div></header>
            <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
              <table className="table">
                <thead><tr><th>Student</th><th className="r">Risk</th><th className="r">Cohort rank</th><th>Tier</th><th>Main driver</th><th>Next step</th></tr></thead>
                <tbody>{result.rows.slice(0, 200).map((r) => <tr key={r.reference}><td className="mono">{r.reference}</td><td className="r mono">{pct(r.risk_probability)}</td><td className="r mono">{r.cohort_percentile.toFixed(0)}th</td><td><TierBadge tier={r.risk_tier} /></td><td className="secondary">{r.top_driver ?? "—"}</td><td className="secondary">{r.intervention_level}</td></tr>)}</tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <header className="card-header"><div><h2 className="card-title">How each input was obtained</h2><div className="card-sub">Ordered by how much the model relies on it.</div></div></header>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Model input</th><th>From</th><th>How</th><th className="r">Weight</th></tr></thead>
                <tbody>{result.fit.features.map((f) => <tr key={f.feature}><td style={{ fontWeight: 600 }}>{f.label}</td><td className="mono">{f.column ?? "—"}</td><td><span className={`origin origin-${f.origin}`}>{f.origin_text}</span>{f.note && <div className="muted" style={{ fontSize: 12.5 }}>{f.note}</div>}</td><td className="r mono">{pct(f.importance, 1)}</td></tr>)}</tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
