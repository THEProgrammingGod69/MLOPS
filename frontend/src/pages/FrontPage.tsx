import { api } from "../lib/api";
import { int, ms, pct, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";
import { useLedger } from "../lib/ledger";
import { TierBadge } from "../components/ui";

function RiskHistogram({ bins, threshold }: { bins: number[]; threshold: number }) {
  const peak = Math.max(1, ...bins);
  return (
    <div>
      <div className="histogram" role="img" aria-label="Distribution of predicted dropout risk in the live window">
        {bins.map((value, i) => (
          <div key={i} className={`bar ${(i + 0.5) / bins.length >= threshold ? "hot" : ""}`} style={{ height: `${(value / peak) * 100}%` }} title={`${Math.round((i / bins.length) * 100)}–${Math.round(((i + 1) / bins.length) * 100)}%: ${int(value)}`} />
        ))}
        <div className="limit" style={{ left: `${threshold * 100}%` }} />
      </div>
      <div className="scale-labels mt-8"><span>0%</span><span style={{ color: "var(--accent)" }}>{pct(threshold, 0)} alert line</span><span>100%</span></div>
    </div>
  );
}

export default function FrontPage() {
  const { snapshot } = useLedger();
  const summary = useApi(api.monitoringSummary, 6000);
  const recent = useApi(() => api.monitoringRecent(8), 6000);
  const s = summary.data;
  const total = snapshot?.open_count ?? 0;
  const mine = snapshot?.open_user_count ?? 0;
  const threshold = snapshot?.threshold ?? 0.5;
  const top = snapshot?.open[0];

  return (
    <>
      <div className="front mb-16">
        <article>
          <div className="kicker">Today’s lead</div>
          <h2 className="display" style={{ fontSize: "clamp(44px, 6.4vw, 88px)", lineHeight: 0.98, margin: "10px 0 16px" }}>
            {mine > 0 ? `${int(mine)} ${mine === 1 ? "student needs" : "students need"} someone today.` : total > 0 ? `${int(total)} students have crossed the line.` : "Nobody has crossed the line."}
          </h2>
          <p className="prose" style={{ fontSize: 17 }}>
            {mine > 0
              ? <>Every one of them scored {pct(threshold, 0)} or higher. {top?.top_driver ? <>The most urgent case is driven by <strong>{top.top_driver.toLowerCase()}</strong>. </> : null}Each is waiting on the alert desk and firing in Grafana.</>
              : <>The alert line sits at {pct(threshold, 0)} dropout probability. The cases above it now come from the built-in demo stream. Assess a student or bring your own file and yours will appear here and in Grafana within seconds.</>}
          </p>
          <div className="row-wrap mt-16">
            <a className="btn btn-primary" href="#/desk">Open the alert desk</a>
            <a className="btn" href="#/intake">Bring your institution’s data</a>
          </div>
        </article>
        <section aria-label="Risk distribution">
          <div className="kicker" style={{ color: "var(--text-secondary)" }}>The shape of risk</div>
          <h3 className="display" style={{ fontSize: 26, margin: "8px 0 14px" }}>Last {int(s?.window.size)} students scored</h3>
          {s ? <RiskHistogram bins={s.window.risk_histogram} threshold={threshold} /> : <div className="loading">Reading the wire…</div>}
          <p className="muted" style={{ fontSize: 13.5, marginBottom: 0 }}>Bars to the right of the red line open a case automatically.</p>
        </section>
        <aside aria-label="Instrument readings">
          <div className="kicker" style={{ color: "var(--text-secondary)" }}>Instruments</div>
          <ul className="leaders mt-8">
            <li><span>Students scored</span><b>{int(s?.totals.predictions)}</b></li>
            <li><span>Mean risk</span><b>{pct(s?.window.mean_risk_probability)}</b></li>
            <li><span>Sent to review</span><b>{pct(s?.window.human_review_rate)}</b></li>
            <li><span>Drifting features</span><b>{s?.drift.ready ? int(s.drift.moderate + s.drift.substantial) : "—"}</b></li>
            <li><span>Latency p95</span><b>{ms(s?.window.latency_ms.p95)}</b></li>
            <li><span>Failed requests</span><b>{int(s?.totals.errors)}</b></li>
          </ul>
        </aside>
      </div>

      <section className="card">
        <header className="card-header"><div><h2 className="card-title">Latest entries</h2><div className="card-sub">Every prediction is logged without student identifiers.</div></div><a href="#/observatory">Full observatory</a></header>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>When</th><th>Entry</th><th>Course</th><th className="r">Risk</th><th>Tier</th><th>Main driver</th></tr></thead>
            <tbody>
              {(recent.data?.items ?? []).map((r) => (
                <tr key={r.prediction_id}>
                  <td className="muted nowrap">{timeAgo(r.timestamp)}</td>
                  <td className="mono">{r.prediction_id.slice(0, 10)}</td>
                  <td className="mono">{r.code_module} {r.code_presentation}</td>
                  <td className="r num mono">{pct(r.risk_probability)}</td>
                  <td><TierBadge tier={r.risk_tier} /></td>
                  <td className="secondary">{r.top_driver ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
