import type { FeatureRecord, FeatureSpec } from "./types";

/** RFC 4180 parser: quoted fields, escaped quotes, CRLF/LF, trailing newline. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  const src = text.replace(/^﻿/, "");
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') { field += '"'; i++; } else quoted = false;
      } else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.some((c) => c.trim() !== "")) rows.push(row);
      row = [];
    } else field += ch;
  }
  row.push(field);
  if (row.some((c) => c.trim() !== "")) rows.push(row);
  return rows;
}

const escape = (value: unknown): string => {
  const s = value === null || value === undefined ? "" : String(value);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export const toCsv = (header: string[], rows: unknown[][]): string =>
  [header, ...rows].map((r) => r.map(escape).join(",")).join("\n") + "\n";

export function download(filename: string, content: string, type = "text/csv;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export interface ParsedCohort {
  students: FeatureRecord[];
  errors: string[];
  missingColumns: string[];
}

const NULL_TOKENS = new Set(["", "na", "nan", "null", "none", "?"]);

/** Validate a CSV against the feature schema. Optional columns: record_id, gender. */
export function toStudents(rows: string[][], features: FeatureSpec[], maxErrors = 12): ParsedCohort {
  if (rows.length === 0) return { students: [], errors: ["The file is empty."], missingColumns: [] };
  const header = rows[0].map((h) => h.trim());
  const index = new Map(header.map((h, i) => [h, i]));
  const missingColumns = features.map((f) => f.name).filter((n) => !index.has(n));
  if (missingColumns.length) return { students: [], errors: [], missingColumns };

  const errors: string[] = [];
  const students: FeatureRecord[] = [];
  rows.slice(1).forEach((cells, r) => {
    const line = r + 2;
    const student: FeatureRecord = {};
    let ok = true;
    for (const spec of features) {
      const raw = (cells[index.get(spec.name)!] ?? "").trim();
      if (spec.kind === "category") {
        if (!raw) { ok = false; errors.length < maxErrors && errors.push(`Line ${line}: ${spec.name} is empty`); }
        student[spec.name] = raw;
        continue;
      }
      if (NULL_TOKENS.has(raw.toLowerCase())) {
        if (!spec.nullable) { ok = false; errors.length < maxErrors && errors.push(`Line ${line}: ${spec.name} cannot be empty`); }
        student[spec.name] = null;
        continue;
      }
      const value = Number(raw);
      if (Number.isNaN(value)) {
        ok = false;
        errors.length < maxErrors && errors.push(`Line ${line}: ${spec.name} = "${raw}" is not a number`);
      } else if (spec.kind === "integer" && !Number.isInteger(value)) {
        ok = false;
        errors.length < maxErrors && errors.push(`Line ${line}: ${spec.name} must be a whole number`);
      } else if (spec.min !== null && spec.min >= 0 && value < 0) {
        ok = false;
        errors.length < maxErrors && errors.push(`Line ${line}: ${spec.name} cannot be negative`);
      }
      student[spec.name] = value;
    }
    const recordId = index.has("record_id") ? (cells[index.get("record_id")!] ?? "").trim() : "";
    student.record_id = recordId || `row-${line}`;
    if (index.has("gender")) {
      const g = (cells[index.get("gender")!] ?? "").trim();
      if (g) student.gender = g;
    }
    if (ok) students.push(student);
  });
  return { students, errors, missingColumns };
}
