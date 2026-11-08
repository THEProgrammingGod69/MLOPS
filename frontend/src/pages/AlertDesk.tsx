import { useState } from "react";
import { api } from "../lib/api";
import { pct, timeAgo } from "../lib/format";
import { useApi } from "../lib/hooks";
import { useLedger } from "../lib/ledger";
import type { AlertCase } from "../lib/types";
import { Empty, Segmented, TierBadge } from "../components/ui";

function CaseSlip({ item, name, onAck }: { item: AlertCase; name?: string; onAck: (assignee: string, note: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [assignee, setAssignee] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <article className={`case ${item.origin === "simulator" ? "demo" : ""}`}>
      <div className="pct">{pct(item.risk_probability, 0)}</div>
      <div>
        <div className="row-wrap">
          <h3>{name ?? item.ref}</h3>
          <TierBadge tier={item.risk_tier} />
          {item.origin === "simulator" && <span className="badge badge-neutral">Demo stream</span>}
        </div>
        <div className="secondary" style={{ fontSize: 14 }}>{item.top_driver ? <>Main driver: <strong>{item.top_driver}</strong> · </> : null}{item.intervention_level}</div>
        <div className="muted mono" style={{ marginTop: 2 }}>{item.ref} in Grafana · {item.cohort} · raised {timeAgo(item.raised_at)}</div>
        {open && (
          <div className="form-grid mt-16">
            <div className="field"><label className="field-label" htmlFor={`a-${item.id}`}>Assign to</label><input id={`a-${item.id}`} className="input" value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="Advisor name" /></div>
            <div className="field"><label className="field-label" htmlFor={`n-${item.id}`}>Note</label><input id={`n-${item.id}`} className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happens next" /></div>
          </div>
        )}
      </div>
      <div className="row-wrap">
        {open
          ? <button className="btn btn-primary btn-sm" disabled={busy} onClick={async () => { setBusy(true); await onAck(assignee, note).finally(() => setBusy(false)); }}>Confirm</button>
          : <button className="btn btn-sm" onClick={() => setOpen(true)}>Acknowledge</button>}
      </div>
    </article>
  );
}

export default function AlertDesk() {
  const { snapshot, acknowledge, names } = useLedger();
  const meta = useApi(api.meta);
  const [view, setView] = useState<"yours" | "all" | "closed">("yours");
  const grafana = meta.data?.links.grafana;
  const open = snapshot?.open ?? [];
  const list = view === "yours" ? open.filter((c) => c.origin === "user") : open;
  const threshold = snapshot ? pct(snapshot.threshold, 0) : "50%";

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Alert desk</h1>
          <p className="page-desc">Any student scored at {threshold} or above opens a case here and fires <span className="mono">StudentDropoutRiskAbove50</span> in Prometheus. Acknowledging a case clears it from Grafana.</p>
        </div>
        <div className="page-actions">
          {grafana && <a className="btn" href={`${grafana}/d/mlops-monitoring`} target="_blank" rel="noreferrer">See them in Grafana</a>}
          <Segmented label="Cases shown" value={view} onChange={setView} options={[{ value: "yours", label: `Yours (${snapshot?.open_user_count ?? 0})` }, { value: "all", label: `All open (${open.length})` }, { value: "closed", label: "Acknowledged" }]} />
        </div>
      </div>

      {view === "closed" ? (
        (snapshot?.acknowledged.length ?? 0) === 0 ? <Empty title="Nothing acknowledged yet" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Student</th><th className="r">Risk</th><th>Assigned to</th><th>Note</th><th>Acknowledged</th></tr></thead>
              <tbody>{snapshot!.acknowledged.map((c) => <tr key={c.id}><td>{names[c.ref] ?? c.ref}</td><td className="r mono">{pct(c.risk_probability, 0)}</td><td>{c.assignee ?? "—"}</td><td className="secondary">{c.note ?? "—"}</td><td className="muted">{c.acknowledged_at ? timeAgo(c.acknowledged_at) : "—"}</td></tr>)}</tbody>
            </table>
          </div>
        )
      ) : list.length === 0 ? (
        <Empty title={view === "yours" ? "No cases of yours are open" : "The desk is clear"}>
          Run someone through the <a href="#/case">case file</a> or upload a cohort at <a href="#/intake">intake</a>. Anyone at {threshold} or above lands here.
        </Empty>
      ) : (
        <div>{list.map((item) => <CaseSlip key={item.id} item={item} name={names[item.ref]} onAck={(a, n) => acknowledge(item.id, a, n)} />)}</div>
      )}
    </>
  );
}
