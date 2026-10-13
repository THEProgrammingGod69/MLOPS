import { useMemo, useRef, useState } from "react";
import { ArrowDownUp, Download, FileSpreadsheet, FileUp, Loader2, Play, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { download, parseCsv, toCsv, toStudents, type ParsedCohort } from "../lib/csv";
import { int, ms, pct } from "../lib/format";
import { useApi } from "../lib/hooks";
import { CHART_INIT, TIER_COLOR, TIER_LABEL, useChartPalette } from "../lib/theme";
import { RISK_TIERS, type BatchResponse, type BatchRow, type RiskTier } from "../lib/types";
import { Card, ChartTooltip, Empty, ErrorState, InlineBar, Loading, Segmented, StatTile, TierBadge } from "../components/ui";

type SortKey = "index" | "risk_probability" | "record_id";

export default function Batch() {
  const palette = useChartPalette();
  const schema = useApi(api.schema);
  const [cohort, setCohort] = useState<(ParsedCohort & { name: string }) | null>(null);
  const [explain, setExplain] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<BatchResponse | null>(null);
  const [filter, setFilter] = useState<"ALL" | RiskTier>("ALL");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "risk_probability", desc: true });
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const features = schema.data?.features ?? [];
  const columns = features.map((f) => f.name);

  function loadText(text: string, name: string) {
    setResponse(null);
    setError(null);
    setCohort({ ...toStudents(parseCsv(text), features), name });
  }

  function onFile(file: File | undefined) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => loadText(String(reader.result ?? ""), file.name);
    reader.onerror = () => setError("Could not read the file.");
    reader.readAsText(file);
  }

  function templateCsv(): string {
    const samples = schema.data?.samples ?? [];
    return toCsv(["record_id", ...columns, "gender"],
      samples.map((s, i) => [`student-${i + 1}`, ...columns.map((c) => s.features[c]), i % 2 ? "F" : "M"]));
  }

  async function run() {
    if (!cohort?.students.length) return;
    setBusy(true);
    setError(null);
    try {
      setResponse(await api.predictBatch(cohort.students, explain));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const rows = useMemo(() => {
    if (!response) return [];
    const filtered = response.results.filter((r) => filter === "ALL" || r.risk_tier === filter);
    const dir = sort.desc ? -1 : 1;
    return [...filtered].sort((a, b) => {
      const av = a[sort.key] ?? "";
      const bv = b[sort.key] ?? "";
      return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
    });
  }, [response, filter, sort]);

  function exportResults() {
    if (!response) return;
    download(`risk_scores_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.csv`, toCsv(
      ["record_id", "risk_probability", "risk_tier", "intervention_level", "human_review_required",
        "fairness_adjusted_decision", "fairness_status", "missing_features", "top_drivers", "model_version"],
      response.results.map((r: BatchRow) => [
        r.record_id, r.risk_probability.toFixed(6), r.risk_tier, r.intervention_level, r.human_review_required,
        r.fairness_adjusted_decision, r.fairness_status, r.missing_features.join(";"),
        (r.top_drivers ?? []).map((d) => d.label).join(";"), response.model_version,
      ]),
    ));
  }

  const header = (key: SortKey, label: string, className = "") => (
    <th className={`sortable ${className}`} onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))}
      aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}>
      <span className="row" style={{ gap: 4, display: "inline-flex" }}>{label}<ArrowDownUp size={11} /></span>
    </th>
  );

  if (schema.loading) return <Loading label="Loading feature schema…" />;
  if (schema.error) return <ErrorState message={schema.error} onRetry={schema.reload} />;

  const tierData = response ? RISK_TIERS.map((t) => ({ tier: t, name: TIER_LABEL[t], count: response.summary.tier_counts[t] ?? 0 })) : [];

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Batch scoring</h1>
          <p className="page-desc">
            Score a whole cohort from a CSV with the 21 Day-28 features (plus optional <span className="mono">record_id</span> and{" "}
            <span className="mono">gender</span>). Rows are validated in the browser before anything is sent.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => download("cohort_template.csv", templateCsv())}><Download size={14} /> CSV template</button>
          <button className="btn" onClick={() => loadText(templateCsv(), "sample cohort (4 archetypes)")}><Users size={14} /> Load sample cohort</button>
        </div>
      </div>

      <div className="grid grid-3 mb-16">
        <div className="span-2">
          <div className={`dropzone ${over ? "over" : ""}`} role="button" tabIndex={0}
            onClick={() => fileInput.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); onFile(e.dataTransfer.files[0]); }}>
            <FileUp size={26} style={{ marginBottom: 6 }} />
            <div style={{ fontWeight: 650, color: "var(--text-primary)" }}>Drop a CSV here or click to browse</div>
            <div className="muted" style={{ fontSize: 12.5 }}>Empty, NA or ? cells are read as missing for the four nullable features. Up to 2,000 rows per run.</div>
            <input ref={fileInput} type="file" accept=".csv,text/csv" hidden onChange={(e) => onFile(e.target.files?.[0])} />
          </div>
        </div>
        <Card title="Run" subtitle={cohort ? cohort.name : "No file loaded"}>
          {cohort ? (
            <div className="stack" style={{ gap: 10 }}>
              <div className="spread"><span className="secondary">Valid rows</span><strong className="num">{int(cohort.students.length)}</strong></div>
              <div className="spread"><span className="secondary">Rejected rows</span><strong className="num">{cohort.errors.length ? `${cohort.errors.length}+` : "0"}</strong></div>
              <label className="check"><input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} /> Include top risk drivers (SHAP)</label>
              <button className="btn btn-primary" disabled={busy || cohort.students.length === 0 || cohort.students.length > 2000} onClick={run}>
                {busy ? <Loader2 size={15} className="spin" /> : <Play size={15} />} Score {int(cohort.students.length)} students
              </button>
              {cohort.students.length > 2000 && <span className="error-box" style={{ fontSize: 12.5 }}>Split the file: the API accepts 2,000 rows per request.</span>}
            </div>
          ) : (
            <span className="muted">Load a file or the sample cohort to begin.</span>
          )}
        </Card>
      </div>

      {cohort?.missingColumns.length ? (
        <div className="mb-16"><ErrorState message={`Missing required columns: ${cohort.missingColumns.join(", ")}. Download the template for the expected header.`} /></div>
      ) : null}
      {cohort?.errors.length ? (
        <div className="callout callout-warn mb-16">
          <FileSpreadsheet size={16} />
          <div><strong>Some rows were skipped.</strong><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{cohort.errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
        </div>
      ) : null}
      {error && <div className="mb-16"><ErrorState message={error} onRetry={run} /></div>}

      {response && (
        <>
          <div className="grid grid-4 mb-16">
            <StatTile label="Students scored" value={int(response.summary.count)} foot={`${ms(response.latency_ms)} end to end`} />
            <StatTile label="Need human review" value={int(response.summary.human_review_count)} foot={pct(response.summary.human_review_rate)} />
            <StatTile label="Mean risk" value={pct(response.summary.mean_risk_probability)} foot={`median ${pct(response.summary.median_risk_probability)}`} />
            <StatTile label="Highest risk" value={pct(response.summary.max_risk_probability)} foot={`model ${response.model_version}`} />
          </div>

          <div className="grid grid-3">
            <Card title="Tier distribution" subtitle="Students per risk tier in this run">
              <div className="chart" style={{ height: 230 }}>
                <ResponsiveContainer initialDimension={CHART_INIT}>
                  <BarChart data={tierData} margin={{ top: 16, right: 8, left: -14, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke={palette.grid} />
                    <XAxis dataKey="name" tickLine={false} stroke={palette.axis} tick={{ fill: palette.muted }} />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: palette.muted }} />
                    <Tooltip cursor={{ fill: palette.track, opacity: 0.4 }} content={<ChartTooltip format={(v) => `${int(v)} students`} />} />
                    <Bar dataKey="count" name="Students" radius={[4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false}
                      label={{ position: "top", fill: palette.text, fontSize: 12 }}>
                      {tierData.map((d) => <Cell key={d.tier} fill={TIER_COLOR[d.tier]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card title="Scored students" className="span-2" flush
              actions={<>
                <Segmented label="Filter by tier" value={filter} onChange={setFilter}
                  options={[{ value: "ALL", label: "All" }, ...RISK_TIERS.map((t) => ({ value: t, label: TIER_LABEL[t] }))]} />
                <button className="btn btn-sm" onClick={exportResults}><Download size={13} /> Export CSV</button>
              </>}>
              {rows.length === 0 ? <Empty title="No students in this tier" /> : (
                <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
                  <table className="table">
                    <thead>
                      <tr>
                        {header("record_id", "Record")}
                        {header("risk_probability", "Risk", "r")}
                        <th>Tier</th><th>Intervention</th><th>Review</th><th>Top drivers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.index}>
                          <td className="mono">{r.record_id ?? r.index + 1}</td>
                          <td className="r num">
                            <span className="row" style={{ justifyContent: "flex-end" }}>
                              <InlineBar value={r.risk_probability} color={TIER_COLOR[r.risk_tier]} />{pct(r.risk_probability)}
                            </span>
                          </td>
                          <td><TierBadge tier={r.risk_tier} /></td>
                          <td>{r.intervention_level}</td>
                          <td>{r.human_review_required ? <strong>Yes</strong> : <span className="muted">No</span>}</td>
                          <td className="secondary" style={{ fontSize: 12.5 }}>{r.top_drivers?.map((d) => d.label).join(", ") || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
