import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { pct } from "../lib/format";
import { useApi, useDebounced } from "../lib/hooks";
import { useLedger } from "../lib/ledger";
import type { Contribution, FeatureRecord, FeatureSpec, Prediction, RescuePlan, SchemaPayload } from "../lib/types";
import { ContributionChart } from "../components/ContributionChart";
import { ErrorState, Loading } from "../components/ui";

type FormState = Record<string, string | null>;

const toForm = (record: FeatureRecord): FormState =>
  Object.fromEntries(Object.entries(record).map(([k, v]) => [k, v === null ? null : String(v)]));

function parse(schema: SchemaPayload, form: FormState, gender: string) {
  const errors: Record<string, string> = {};
  const payload: FeatureRecord = {};
  for (const spec of schema.features) {
    const raw = form[spec.name];
    if (spec.kind === "category") {
      if (!raw) errors[spec.name] = "Required";
      payload[spec.name] = raw ?? "";
      continue;
    }
    if (raw === null) {
      if (!spec.nullable) errors[spec.name] = "Required";
      payload[spec.name] = null;
      continue;
    }
    const value = Number(raw);
    if (raw === undefined || raw.trim() === "" || Number.isNaN(value)) errors[spec.name] = "Enter a number";
    else if (spec.kind === "integer" && !Number.isInteger(value)) errors[spec.name] = "Whole number";
    else if (spec.min !== null && value < spec.min) errors[spec.name] = `Min ${spec.min}`;
    else if (spec.max !== null && value > spec.max) errors[spec.name] = `Max ${spec.max}`;
    payload[spec.name] = value;
  }
  if (gender) payload.gender = gender;
  return { payload, errors };
}

function Field({ spec, value, error, options, onChange }: { spec: FeatureSpec; value: string | null; error?: string; options?: string[]; onChange: (v: string | null) => void }) {
  const id = `f-${spec.name}`;
  if (spec.kind === "category") {
    return (
      <div className="field">
        <label className="field-label" htmlFor={id}>{spec.label}</label>
        <select id={id} className="select" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          {(options ?? spec.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    );
  }
  const isNull = value === null;
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}><span>{spec.label}</span>{error && <span className="error-box">{error}</span>}</label>
      <div className="input-wrap">
        <input id={id} className="input num" type="number" inputMode="decimal" value={isNull ? "" : value ?? ""} placeholder={isNull ? "not recorded" : undefined} disabled={isNull}
          min={spec.min ?? undefined} max={spec.max ?? undefined} step={spec.step ?? (spec.kind === "integer" ? 1 : "any")} aria-invalid={Boolean(error)} onChange={(e) => onChange(e.target.value)} />
        {spec.unit && <span className="input-unit">{spec.unit}</span>}
      </div>
      {spec.nullable && (
        <label className="check"><input type="checkbox" checked={isNull} onChange={(e) => onChange(e.target.checked ? null : String(spec.default ?? 0))} />{spec.null_label}</label>
      )}
    </div>
  );
}

function RiskScale({ value, cuts }: { value: number; cuts: number[] }) {
  return (
    <div>
      <div className="scale" role="img" aria-label={`Risk ${pct(value)} on a scale from 0 to 100 percent`}>
        <div className="track" />
        {cuts.map((c) => <div key={c} className={`tick ${c === 0.5 ? "line" : ""}`} style={{ left: `${c * 100}%` }} />)}
        <div className="marker" style={{ left: `${value * 100}%` }} />
      </div>
      <div className="scale-labels"><span>0</span><span style={{ color: "var(--accent)" }}>50% alert</span><span>100</span></div>
    </div>
  );
}

const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

function plainBrief(p: Prediction, plan: RescuePlan | null): string {
  const list: Contribution[] = p.explanation?.contributions ?? [];
  const up = list.filter((c) => c.contribution > 0).slice(0, 2).map((c) => lower(c.label));
  const down = list.filter((c) => c.contribution < 0).slice(0, 1).map((c) => lower(c.label));
  let text = `The model puts this student's chance of withdrawing at ${pct(p.risk_probability, 0)}.`;
  if (up.length) text += ` The strongest warning ${up.length > 1 ? "signs are" : "sign is"} ${up.join(" and ")}.`;
  if (down.length) text += ` Working in their favour: ${down[0]}.`;
  if (plan?.steps.length) text += ` ${plan.reaches_target ? "A realistic plan" : "The best available plan"} of ${plan.steps.length} step${plan.steps.length > 1 ? "s" : ""} would bring the estimate to ${pct(plan.end_probability, 0)}.`;
  return text;
}

function outreach(plan: RescuePlan | null): string {
  const steps = (plan?.steps ?? []).slice(0, 3).map((s) => `  • ${s.action}`).join("\n");
  return `Hi,\n\nI wanted to check in and see how the course is going for you. It can be hard to keep up in the first few weeks, and you are not on your own with it.\n\n${steps ? `A few things that could really help right now:\n${steps}\n\n` : ""}Could we find 15 minutes this week to talk through what would make this easier?\n\nWarm regards,\nYour advisor`;
}

function RescueSection({ plan, loading }: { plan: RescuePlan | null; loading: boolean }) {
  if (loading && !plan) return <div className="loading"><Loader2 size={14} className="spin" /> Working out the shortest way back…</div>;
  if (!plan) return null;
  if (plan.already_below_target) return <p className="prose">This student is already below the {pct(plan.target, 0)} alert line, so no rescue plan is needed.</p>;
  return (
    <div>
      <p className="prose" style={{ marginTop: 0 }}>
        {plan.reaches_target ? <>The fewest actions that bring this student under {pct(plan.target, 0)}.</> : <>No combination of these actions reaches {pct(plan.target, 0)}. This is the furthest the model moves.</>}{" "}
        From <strong>{pct(plan.start_probability, 0)}</strong> to <strong>{pct(plan.end_probability, 0)}</strong>.
      </p>
      {plan.steps.map((step, i) => (
        <div key={step.id} className="rescue-step">
          <span className="n">{i + 1}</span>
          <div><div style={{ fontWeight: 600 }}>{step.action}</div><div className="muted" style={{ fontSize: 13 }}>{step.owner}</div></div>
          <span className="delta">{(step.risk_change * 100).toFixed(1)} pts</span>
        </div>
      ))}
      <p className="muted" style={{ fontSize: 13 }}>Shows how the model responds to changed inputs. It suggests where help may matter most; it does not promise an outcome.</p>
    </div>
  );
}

export default function CaseFile() {
  const schema = useApi(api.schema);
  const { refresh } = useLedger();
  const [form, setForm] = useState<FormState | null>(null);
  const [gender, setGender] = useState("");
  const [reference, setReference] = useState("");
  const [preset, setPreset] = useState<string | null>("disengaging");
  const [result, setResult] = useState<Prediction | null>(null);
  const [plan, setPlan] = useState<RescuePlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const requestId = useRef(0);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (schema.data && !form) {
      const start = schema.data.samples.find((s) => s.id === "disengaging") ?? schema.data.samples[0];
      setForm(toForm(start.features));
    }
  }, [schema.data, form]);

  const parsed = useMemo(() => (schema.data && form ? parse(schema.data, form, gender) : null), [schema.data, form, gender]);
  const valid = parsed !== null && Object.keys(parsed.errors).length === 0;
  const debounced = useDebounced(parsed?.payload, 450);

  async function score(payload: FeatureRecord, reveal = false) {
    const id = ++requestId.current;
    setBusy(true);
    setError(null);
    setPlan(null);
    try {
      const prediction = await api.predict(payload, true, reference.trim() || undefined);
      if (id !== requestId.current) return;
      setResult(prediction);
      refresh();
      if (reveal) window.requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
      const rescue = await api.rescue(payload);
      if (id === requestId.current) setPlan(rescue);
      const body = JSON.stringify({ prediction: prediction.prediction_id, model: prediction.model_version, inputs: payload, risk: prediction.risk_probability });
      if (window.crypto?.subtle) {
        const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(body));
        if (id === requestId.current) setReceipt(Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join(""));
      }
    } catch (e) {
      if (id === requestId.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  useEffect(() => {
    if (live && valid && debounced) void score(debounced);
  }, [live, debounced]);

  if (schema.loading) return <Loading label="Opening the file…" />;
  if (schema.error || !schema.data) return <ErrorState message={schema.error ?? "Schema unavailable"} onRetry={schema.reload} />;
  if (!form || !parsed) return <Loading />;

  const sch = schema.data;
  const update = (name: string, value: string | null) => {
    setPreset(null);
    setForm((current) => {
      const next = { ...current!, [name]: value };
      if (name === "code_module") {
        const presentations = Object.keys(sch.course_catalog[value ?? ""] ?? {});
        if (!presentations.includes(next.code_presentation ?? "")) next.code_presentation = presentations[presentations.length - 1];
      }
      if (name === "code_module" || name === "code_presentation") {
        const length = sch.course_catalog[next.code_module ?? ""]?.[next.code_presentation ?? ""];
        if (length) next.module_presentation_length = String(length);
      }
      return next;
    });
  };
  const presentations = Object.keys(sch.course_catalog[form.code_module ?? ""] ?? {});
  const contributions = result?.explanation?.contributions ?? [];
  const assess = () => void score(parsed.payload, true);

  return (
    <>
      <div className="page-header no-print">
        <div>
          <h1 className="page-title">Case file</h1>
          <p className="page-desc">One student at day 28. You get the probability, why the model thinks so, and the smallest set of actions that would change its mind.</p>
        </div>
        <div className="page-actions">
          <label className="check"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Re-score as I type</label>
          <button className="btn btn-primary" disabled={!valid || busy} onClick={assess}>{busy && <Loader2 size={15} className="spin" />}Assess this student</button>
        </div>
      </div>

      <div className="split">
        <div className="stack no-print">
          <div>
            <div className="kicker" style={{ color: "var(--text-secondary)" }}>Start from an archetype</div>
            <div className="row-wrap mt-8">
              {sch.samples.map((sample) => <button key={sample.id} type="button" title={sample.description} className={`chip ${preset === sample.id ? "active" : ""}`} onClick={() => { setForm(toForm(sample.features)); setPreset(sample.id); }}>{sample.label}</button>)}
            </div>
          </div>
          <div className="form-grid">
            <div className="field"><label className="field-label" htmlFor="f-ref">Student reference</label><input id="f-ref" className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Optional: roll no. or ID" maxLength={80} /><span className="field-hint">Grafana only ever sees a pseudonym of this.</span></div>
            <div className="field"><label className="field-label" htmlFor="f-gender">{sch.sensitive_attribute.label}</label><select id="f-gender" className="select" value={gender} onChange={(e) => setGender(e.target.value)}><option value="">Not provided</option>{sch.sensitive_attribute.options.map((o) => <option key={o} value={o}>{o === "M" ? "Male" : "Female"}</option>)}</select><span className="field-hint">Used only by the fairness step, never for the risk score.</span></div>
          </div>
          {sch.groups.map((group) => (
            <section key={group.id} className="card">
              <header className="card-header"><div><h2 className="card-title">{group.label}</h2><div className="card-sub">{group.description}</div></div></header>
              <div className="form-grid">
                {sch.features.filter((f) => f.group === group.id).map((spec) => <Field key={spec.name} spec={spec} value={form[spec.name] ?? null} error={parsed.errors[spec.name]} options={spec.name === "code_presentation" ? presentations : undefined} onChange={(v) => update(spec.name, v)} />)}
              </div>
            </section>
          ))}
          <div><button className="btn btn-primary" disabled={!valid || busy} onClick={assess}>Assess this student</button>{!valid && <span className="error-box" style={{ marginLeft: 12 }}>Fix {Object.keys(parsed.errors).length} field(s) first.</span>}</div>
        </div>

        <div className="stack sticky" ref={resultRef} style={{ scrollMarginTop: 16 }}>
          {error && <ErrorState message={error} />}
          {!result ? (
            <div className="card"><p className="brief" style={{ color: "var(--text-muted)" }}>Choose an archetype or fill in the ledger, then press assess. The verdict is stamped here.</p></div>
          ) : (
            <div className={busy ? "stack refreshing" : "stack"}>
              <section className="card">
                <div className="kicker">Chance of withdrawing</div>
                <div className="verdict">
                  <div className="big-number">{(result.risk_probability * 100).toFixed(1)}<small>%</small></div>
                  <div className={`stamp ${result.risk_tier}`} key={result.prediction_id}>{result.risk_tier}</div>
                </div>
                <RiskScale value={result.risk_probability} cuts={[0.2, 0.3, 0.5]} />
                <p className="secondary" style={{ marginBottom: 0 }}>Recommended: <strong>{result.intervention_level}</strong>{result.human_review_required ? ". A human advisor must review this." : "."}</p>
                {result.alert && (
                  <div className="alert-slip mt-16"><strong>Alert raised.</strong> On the <a href="#/desk">alert desk</a> now, and firing in Grafana as <span className="mono">{result.alert.ref}</span> within about 10 seconds.</div>
                )}
              </section>

              <section className="card"><h2 className="card-title">In plain English</h2><p className="brief" style={{ marginBottom: 0 }}>{plainBrief(result, plan)}</p></section>

              <section className="card"><header className="card-header"><h2 className="card-title">Rescue plan</h2></header><RescueSection plan={plan} loading={busy} /></section>

              {result.explanation && <section className="card no-print"><header className="card-header"><div><h2 className="card-title">Why this score</h2><div className="card-sub">SHAP contribution of each input ({result.explanation.backend})</div></div></header><ContributionChart contributions={contributions} /></section>}

              <section className="card no-print">
                <header className="card-header"><div><h2 className="card-title">Draft outreach</h2><div className="card-sub">Supportive by design: it never mentions a score.</div></div>
                  <button className="btn btn-sm" onClick={async () => { await navigator.clipboard?.writeText(outreach(plan)); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }}>{copied ? "Copied" : "Copy"}</button></header>
                <div className="draft">{outreach(plan)}</div>
              </section>

              <section className="card">
                <header className="card-header"><div><h2 className="card-title">Decision receipt</h2><div className="card-sub">Proof of what was scored, by which model.</div></div><button className="btn btn-sm no-print" onClick={() => window.print()}>Print</button></header>
                <dl className="kv">
                  <dt>Prediction</dt><dd>{result.prediction_id}</dd>
                  <dt>Model</dt><dd>{result.model_version}</dd>
                  <dt>Fairness step</dt><dd>{result.fairness_status === "Applied" ? `Applied: ${result.fairness_adjusted_decision === 1 ? "flag" : "no flag"}` : "Not applied"}</dd>
                  <dt>Inputs SHA-256</dt><dd style={{ wordBreak: "break-all" }}>{receipt ?? "computing…"}</dd>
                </dl>
              </section>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
