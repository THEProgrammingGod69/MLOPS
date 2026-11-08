import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { int, pct } from "../lib/format";
import { useApi } from "../lib/hooks";
import { useLedger } from "../lib/ledger";
import type { FeatureRecord, StressResult, TriagePlan } from "../lib/types";
import { Empty, ErrorState, TierBadge } from "../components/ui";

function Mirror({ before, after }: { before: number[]; after: number[] }) {
  const peak = Math.max(1, ...before, ...after);
  return (
    <div className="mirror" role="img" aria-label="Risk distribution before and after the scenario">
      <div className="row-m muted"><span>Risk</span><span style={{ textAlign: "right" }}>Before</span><span>After</span></div>
      {before.map((b, i) => (
        <div className="row-m" key={i}>
          <span>{i * 10}–{(i + 1) * 10}%</span>
          <div className="l"><span style={{ width: `${(b / peak) * 100}%` }} title={String(b)} /></div>
          <div className="rr"><span style={{ width: `${(after[i] / peak) * 100}%` }} title={String(after[i])} /></div>
        </div>
      ))}
    </div>
  );
}

export default function CohortLab() {
  const { cohort } = useLedger();
  const scenarios = useApi(api.scenarios);
  const [hours, setHours] = useState(20);
  const [response, setResponse] = useState(0.6);
  const [plan, setPlan] = useState<TriagePlan | null>(null);
  const [scenario, setScenario] = useState("lms_outage");
  const [stress, setStress] = useState<StressResult | null>(null);
  const [busy, setBusy] = useState<"triage" | "stress" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const students = useMemo<FeatureRecord[]>(() => (cohort?.rows ?? []).map((r) => ({ ...r.features, record_id: r.reference })), [cohort]);

  useEffect(() => {
    if (!students.length) return;
    let live = true;
    setBusy("triage");
    const id = window.setTimeout(() => {
      api.triage(students, hours, response)
        .then((p) => { if (live) { setPlan(p); setError(null); } })
        .catch((e) => { if (live) setError(String(e.message ?? e)); })
        .finally(() => { if (live) setBusy(null); });
    }, 300);
    return () => { live = false; window.clearTimeout(id); };
  }, [students, hours, response]);

  useEffect(() => {
    if (!students.length) return;
    let live = true;
    api.stress(students, scenario)
      .then((s) => { if (live) { setStress(s); setError(null); } })
      .catch((e) => { if (live) setError(String(e.message ?? e)); });
    return () => { live = false; };
  }, [students, scenario]);

  if (!cohort) {
    return (
      <>
        <div className="page-header"><div><h1 className="page-title">Cohort lab</h1><p className="page-desc">Decide where a limited advisor budget does the most good, and see what a bad week would do to a whole cohort.</p></div></div>
        <Empty title="The lab needs a cohort">Score one at <a href="#/intake">intake</a>. The three sample institutions take a single click.</Empty>
      </>
    );
  }

  const active = scenarios.data?.scenarios.find((s) => s.id === scenario);
  const extra = plan ? plan.uplift_vs_naive : 0;

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Cohort lab</h1>
          <p className="page-desc">Working on <strong>{cohort.cohort}</strong>, {int(cohort.count)} students. Decide where a limited advisor budget does the most good, and see what a bad week would do.</p>
        </div>
      </div>
      {error && <div className="mb-16"><ErrorState message={error} /></div>}

      <section className="card mb-16">
        <header className="card-header"><div><h2 className="card-title">Advisor triage</h2><div className="card-sub">Highest risk is not always where a conversation changes the most.</div></div>{busy === "triage" && <Loader2 size={16} className="spin" />}</header>
        <div className="front">
          <div>
            <div className="field"><label className="field-label" htmlFor="hours"><span>Advisor hours this week</span><span className="mono">{hours} h</span></label><input id="hours" type="range" min={1} max={120} value={hours} onChange={(e) => setHours(Number(e.target.value))} /></div>
            <div className="field mt-16"><label className="field-label" htmlFor="resp"><span>Students who respond to outreach</span><span className="mono">{pct(response, 0)}</span></label><input id="resp" type="range" min={0.1} max={1} step={0.05} value={response} onChange={(e) => setResponse(Number(e.target.value))} /></div>
            <p className="muted" style={{ fontSize: 13.5 }}>Critical cases take 45 minutes, high 30. The response rate is your assumption, not something the model knows.</p>
          </div>
          <div>
            <div className="kicker" style={{ color: "var(--text-secondary)" }}>Expected to stay</div>
            <div className="big-number" style={{ fontSize: "clamp(64px, 8vw, 104px)" }}>{plan ? plan.expected_saved.toFixed(1) : "—"}</div>
            <div className="stat-foot">students, from {plan?.selected.length ?? 0} conversations in {Math.round((plan?.used_minutes ?? 0) / 60 * 10) / 10} hours</div>
          </div>
          <div>
            <div className="kicker" style={{ color: "var(--text-secondary)" }}>Against highest-risk-first</div>
            <div className="stat-value">{extra >= 0 ? "+" : ""}{extra.toFixed(1)}</div>
            <div className="stat-foot">students compared with working straight down the list, which would keep {plan?.naive_expected_saved.toFixed(1) ?? "—"}</div>
          </div>
        </div>
        <div className="table-wrap mt-16" style={{ maxHeight: 360, overflowY: "auto" }}>
          <table className="table">
            <thead><tr><th>#</th><th>Student</th><th>Tier</th><th className="r">Risk now</th><th className="r">After plan</th><th className="r">Minutes</th><th>Start with</th></tr></thead>
            <tbody>{(plan?.selected ?? []).slice(0, 60).map((s, i) => <tr key={s.reference}><td className="mono">{i + 1}</td><td className="mono">{s.reference}</td><td><TierBadge tier={s.tier} /></td><td className="r mono">{pct(s.risk, 0)}</td><td className="r mono">{pct(s.risk_after_plan, 0)}</td><td className="r mono">{s.minutes}</td><td className="secondary">{s.actions[0] ?? "—"}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <header className="card-header"><div><h2 className="card-title">Stress test</h2><div className="card-sub">{active?.description ?? "Apply a shock to the whole cohort."}</div></div></header>
        <div className="row-wrap mb-16">{scenarios.data?.scenarios.map((s) => <button key={s.id} className={`chip ${s.id === scenario ? "active" : ""}`} onClick={() => setScenario(s.id)}>{s.label}</button>)}</div>
        {stress && (
          <div className="split">
            <Mirror before={stress.histogram_before} after={stress.histogram_after} />
            <div>
              <div className="kicker">Would newly cross {pct(stress.threshold, 0)}</div>
              <div className="big-number" style={{ fontSize: "clamp(64px, 8vw, 104px)" }}>{int(stress.newly_at_risk)}</div>
              <ul className="leaders">
                <li><span>Alerts before → after</span><b>{int(stress.alerts_before)} → {int(stress.alerts_after)}</b></li>
                <li><span>Mean risk before → after</span><b>{pct(stress.mean_before)} → {pct(stress.mean_after)}</b></li>
                <li><span>Would drop below the line</span><b>{int(stress.recovered)}</b></li>
              </ul>
              {stress.most_exposed.length > 0 && <p className="secondary" style={{ fontSize: 14 }}>Most exposed: {stress.most_exposed.slice(0, 6).map((m) => m.reference).join(", ")}.</p>}
            </div>
          </div>
        )}
      </section>
    </>
  );
}
