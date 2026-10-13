import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, RotateCcw, Scale, Sparkles, UserCheck, Zap } from "lucide-react";
import { api } from "../lib/api";
import { pct } from "../lib/format";
import { useApi, useDebounced } from "../lib/hooks";
import type { FeatureRecord, FeatureSpec, Prediction, SchemaPayload } from "../lib/types";
import { RiskGauge } from "../components/RiskGauge";
import { ContributionChart } from "../components/ContributionChart";
import { Card, Empty, ErrorState, Loading, TierBadge } from "../components/ui";

type FormState = Record<string, string | null>; // null = explicitly missing (nullable features only)

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
    if (raw === undefined || raw.trim() === "" || Number.isNaN(value)) {
      errors[spec.name] = "Enter a number";
    } else if (spec.kind === "integer" && !Number.isInteger(value)) {
      errors[spec.name] = "Whole number";
    } else if (spec.min !== null && value < spec.min) {
      errors[spec.name] = `Min ${spec.min}`;
    } else if (spec.max !== null && value > spec.max) {
      errors[spec.name] = `Max ${spec.max}`;
    }
    payload[spec.name] = value;
  }
  if (gender) payload.gender = gender;
  return { payload, errors };
}

function consistencyWarnings(p: FeatureRecord): string[] {
  const n = (k: string) => (typeof p[k] === "number" ? (p[k] as number) : null);
  const warnings: string[] = [];
  const [c7, c14, total] = [n("vle_clicks_last_7_days"), n("vle_clicks_last_14_days"), n("vle_total_clicks")];
  if (c7 !== null && c14 !== null && c7 > c14) warnings.push("Clicks in the last 7 days exceed clicks in the last 14 days.");
  if (c14 !== null && total !== null && c14 > total) warnings.push("Clicks in the last 14 days exceed total VLE clicks.");
  const parts = ["vle_forum_clicks", "vle_resource_clicks", "vle_quiz_clicks"].map(n);
  if (total !== null && parts.every((x) => x !== null) && (parts as number[]).reduce((a, b) => a + b, 0) > total)
    warnings.push("Forum + resource + quiz clicks exceed total VLE clicks.");
  const subs = n("asm_submission_count");
  const failed = n("asm_failed_count");
  if (subs !== null && failed !== null && failed > subs) warnings.push("More failed assessments than submissions.");
  if (subs === 0 && p.asm_mean_score !== null) warnings.push("A mean score is set although no assessment was submitted.");
  if (subs !== null && subs < 2 && p.asm_score_std !== null) warnings.push("A score spread needs at least two scored submissions.");
  return warnings;
}

function Field(props: {
  spec: FeatureSpec;
  value: string | null;
  error?: string;
  options?: string[];
  onChange: (value: string | null) => void;
}) {
  const { spec, value, error } = props;
  const id = `f-${spec.name}`;
  if (spec.kind === "category") {
    return (
      <div className="field">
        <label className="field-label" htmlFor={id}>{spec.label}</label>
        <select id={id} className="select" value={value ?? ""} onChange={(e) => props.onChange(e.target.value)}>
          {(props.options ?? spec.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <span className="field-hint">{spec.description}</span>
      </div>
    );
  }
  const isNull = value === null;
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        <span>{spec.label}</span>
        {error && <span className="error-box" style={{ fontWeight: 500 }}>{error}</span>}
      </label>
      <div className="input-wrap">
        <input id={id} className="input num" type="number" inputMode="decimal" value={isNull ? "" : value ?? ""}
          placeholder={isNull ? "missing" : undefined} disabled={isNull}
          min={spec.min ?? undefined} max={spec.max ?? undefined} step={spec.step ?? (spec.kind === "integer" ? 1 : "any")}
          aria-invalid={Boolean(error)} onChange={(e) => props.onChange(e.target.value)} />
        {spec.unit && <span className="input-unit">{spec.unit}</span>}
      </div>
      {spec.nullable ? (
        <label className="check">
          <input type="checkbox" checked={isNull}
            onChange={(e) => props.onChange(e.target.checked ? null : String(spec.default ?? 0))} />
          {spec.null_label}
        </label>
      ) : (
        <span className="field-hint">{spec.description}</span>
      )}
    </div>
  );
}

export default function Assess() {
  const schema = useApi(api.schema);
  const model = useApi(api.model);
  const [form, setForm] = useState<FormState | null>(null);
  const [gender, setGender] = useState("");
  const [preset, setPreset] = useState<string | null>("steady");
  const [result, setResult] = useState<Prediction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);
  const requestId = useRef(0);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (schema.data && !form) {
      const steady = schema.data.samples.find((s) => s.id === "steady") ?? schema.data.samples[0];
      setForm(toForm(steady.features));
    }
  }, [schema.data, form]);

  const parsed = useMemo(() => (schema.data && form ? parse(schema.data, form, gender) : null), [schema.data, form, gender]);
  const warnings = parsed ? consistencyWarnings(parsed.payload) : [];
  const valid = parsed !== null && Object.keys(parsed.errors).length === 0;
  const debouncedPayload = useDebounced(parsed?.payload, 450);

  const cuts = useMemo<[number, number, number]>(() => {
    const t = model.data?.risk_tiers;
    return t ? [t.low.max_probability, t.moderate.max_probability, t.high.max_probability] : [0.2, 0.3, 0.5];
  }, [model.data]);

  async function score(payload: FeatureRecord, reveal = false) {
    const id = ++requestId.current;
    setBusy(true);
    setError(null);
    try {
      const prediction = await api.predict(payload, true);
      if (id === requestId.current) {
        setResult(prediction);
        if (reveal) window.requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
      }
    } catch (e) {
      if (id === requestId.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  useEffect(() => {
    if (live && valid && debouncedPayload) score(debouncedPayload);
    // Re-score only when the debounced inputs (or the live toggle) change.
  }, [live, debouncedPayload]);

  if (schema.loading) return <Loading label="Loading feature schema…" />;
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
  const baseProbability = result?.explanation ? 1 / (1 + Math.exp(-result.explanation.base_value)) : null;
  const strongestUp = contributions.find((c) => c.contribution > 0);
  const strongestDown = contributions.find((c) => c.contribution < 0);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Risk assessment</h1>
          <p className="page-desc">
            Enter what is known about a student at day 28. The model returns a dropout probability, the risk tier and
            intervention it maps to, and the features that drove the score.
          </p>
        </div>
        <div className="page-actions">
          <label className="check" title="Re-score automatically while you edit">
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            <Zap size={13} /> Live what-if
          </label>
          <button className="btn btn-primary" disabled={!valid || busy} onClick={() => score(parsed.payload, true)}>
            {busy ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} Assess risk
          </button>
        </div>
      </div>

      <div className="grid assess-layout" style={{ gridTemplateColumns: "minmax(0, 1.05fr) minmax(0, 1fr)", alignItems: "start" }}>
        <div className="stack">
          <Card title="Start from a profile" subtitle="Illustrative archetypes; the model, not the label, decides the tier">
            <div className="row-wrap">
              {sch.samples.map((sample) => (
                <button key={sample.id} type="button" className={`chip ${preset === sample.id ? "active" : ""}`}
                  title={sample.description}
                  onClick={() => { setForm(toForm(sample.features)); setPreset(sample.id); }}>
                  {sample.label}
                </button>
              ))}
              <button type="button" className="chip" onClick={() => {
                setForm(Object.fromEntries(sch.features.map((f) => [f.name, f.default === null ? null : String(f.default)])));
                setPreset(null);
              }}>
                <RotateCcw size={12} /> Cohort medians
              </button>
            </div>
          </Card>

          {sch.groups.map((group) => (
            <Card key={group.id} title={group.label} subtitle={group.description}>
              <div className="form-grid">
                {sch.features.filter((f) => f.group === group.id).map((spec) => (
                  <Field key={spec.name} spec={spec} value={form[spec.name] ?? null} error={parsed.errors[spec.name]}
                    options={spec.name === "code_presentation" ? presentations : undefined}
                    onChange={(v) => update(spec.name, v)} />
                ))}
              </div>
            </Card>
          ))}

          <Card title="Fairness post-processing" subtitle={sch.sensitive_attribute.description}>
            <div className="form-grid">
              <div className="field">
                <label className="field-label" htmlFor="f-gender">{sch.sensitive_attribute.label}</label>
                <select id="f-gender" className="select" value={gender} onChange={(e) => setGender(e.target.value)}>
                  <option value="">Not provided</option>
                  {sch.sensitive_attribute.options.map((o) => <option key={o} value={o}>{o === "M" ? "Male (M)" : o === "F" ? "Female (F)" : o}</option>)}
                </select>
                <span className="field-hint">The risk probability and tier never use this value.</span>
              </div>
            </div>
          </Card>

          {warnings.length > 0 && (
            <div className="callout callout-warn">
              <AlertTriangle size={16} color="var(--warning)" />
              <div><strong>Inputs look inconsistent.</strong> The model will still score them.<ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {warnings.map((w) => <li key={w}>{w}</li>)}
              </ul></div>
            </div>
          )}

          <div className="row-wrap">
            <button className="btn btn-primary" disabled={!valid || busy} onClick={() => score(parsed.payload, true)}>
              {busy ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} Assess risk
            </button>
            {!valid && <span className="error-box" style={{ fontSize: 12.5 }}>Fix {Object.keys(parsed.errors).length} field(s) first.</span>}
          </div>
        </div>

        <div className="stack" ref={resultRef} style={{ scrollMarginTop: 16 }}>
          {error && <ErrorState message={error} />}
          {!result ? (
            <Card>
              <Empty title="No assessment yet" icon={<UserCheck size={28} />}>
                Pick a profile or edit the form, then press <strong>Assess risk</strong>. Turn on live what-if to see the
                score move as you change inputs.
              </Empty>
            </Card>
          ) : (
            <div className={busy ? "refreshing stack" : "stack"}>
              <Card>
                <div className="result-hero">
                  <RiskGauge probability={result.risk_probability} cuts={cuts} />
                  <div className="stack" style={{ gap: 8 }}>
                    <span className="stat-label">Predicted dropout probability</span>
                    <span className="gauge-value">{pct(result.risk_probability)}</span>
                    <div className="row-wrap"><TierBadge tier={result.risk_tier} /><span className="badge badge-neutral">{result.intervention_level}</span></div>
                    {result.human_review_required ? (
                      <div className="callout callout-bad"><AlertTriangle size={15} color="var(--critical)" />Route to a human advisor for review.</div>
                    ) : (
                      <div className="callout callout-good"><CheckCircle2 size={15} color="var(--good)" />No mandatory human review.</div>
                    )}
                  </div>
                </div>
              </Card>

              <Card title="Recommended actions" subtitle="From configs/intervention_config.yaml for this tier">
                <ul className="action-list">
                  {result.recommended_actions.map((a) => <li key={a}><CheckCircle2 size={15} />{a.charAt(0).toUpperCase() + a.slice(1)}</li>)}
                </ul>
                <div className="divider" />
                <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
                  <Scale size={16} color="var(--accent)" style={{ marginTop: 2, flex: "none" }} />
                  <div>
                    <div style={{ fontWeight: 600 }}>
                      Fairness-adjusted decision:{" "}
                      {result.fairness_adjusted_decision === null ? "not applied" : result.fairness_adjusted_decision === 1 ? "flag for support" : "no flag"}
                    </div>
                    <div className="muted" style={{ fontSize: 12.5 }}>{result.fairness_status}. ThresholdOptimizer (equalized odds) on gender.</div>
                  </div>
                </div>
                {result.missing_features.length > 0 && (
                  <div className="callout mt-16"><Info size={15} />
                    <span>Scored with missing values for {result.missing_features.map((f) => sch.features.find((s) => s.name === f)?.label ?? f).join(", ")}. Missingness is itself a signal the model learned.</span>
                  </div>
                )}
              </Card>

              {result.explanation && (
                <Card title="Why this score" subtitle={`SHAP contributions per input (${result.explanation.backend}), top 10 by magnitude`}>
                  <p className="secondary" style={{ marginTop: 0 }}>
                    The model starts from a baseline of <strong>{pct(baseProbability)}</strong>.
                    {strongestUp && <> <strong>{strongestUp.label}</strong> pushes the risk up the most</>}
                    {strongestUp && strongestDown && ","}
                    {strongestDown && <> while <strong>{strongestDown.label}</strong> pulls it down the most</>}, ending at{" "}
                    <strong>{pct(result.risk_probability)}</strong>.
                  </p>
                  <ContributionChart contributions={contributions} />
                </Card>
              )}

              <div className="muted mono" style={{ fontSize: 11.5 }}>
                prediction {result.prediction_id} · model {result.model_version} · {result.latency_ms.toFixed(1)} ms
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
