import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { safeStorageGet, safeStorageSet } from "./hooks";
import type { AdapterResult, AlertCase, AlertSnapshot } from "./types";

const CASES_KEY = "ew-cases-v1";
const COHORT_KEY = "ew-cohort-v1";
const NAMES_KEY = "ew-names-v1"; // pseudonym -> the id this user typed; never leaves the browser

function readJson<T>(key: string): T | null {
  try {
    const raw = safeStorageGet(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

interface LedgerValue {
  snapshot: AlertSnapshot | null;
  cohort: AdapterResult | null;
  names: Record<string, string>;
  remember: (cases: AlertCase[]) => void;
  setCohort: (result: AdapterResult) => void;
  refresh: () => void;
  acknowledge: (id: string, assignee: string, note: string) => Promise<void>;
}

const Ledger = createContext<LedgerValue>({
  snapshot: null, cohort: null, names: {}, remember: () => undefined, setCohort: () => undefined, refresh: () => undefined, acknowledge: async () => undefined,
});

export const useLedger = () => useContext(Ledger);

/**
 * Serverless instances restart empty. The browser keeps this user's open cases and puts
 * them back whenever it notices a new instance, so an alert raised earlier stays on the
 * desk and reappears in Grafana.
 */
export function LedgerProvider({ instance, children }: { instance: number | undefined; children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<AlertSnapshot | null>(null);
  const [cohort, setCohortState] = useState<AdapterResult | null>(() => readJson<AdapterResult>(COHORT_KEY));
  const [names, setNames] = useState<Record<string, string>>(() => readJson<Record<string, string>>(NAMES_KEY) ?? {});
  const kept = useRef<AlertCase[]>(readJson<AlertCase[]>(CASES_KEY) ?? []);
  const lastInstance = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const next = await api.alerts();
      setSnapshot(next);
      const mine = next.open.filter((c) => c.origin === "user");
      kept.current = mine;
      safeStorageSet(CASES_KEY, JSON.stringify(mine));
    } catch {
      /* the next poll retries */
    }
  }, []);

  useEffect(() => {
    if (instance === undefined || instance === lastInstance.current) return;
    lastInstance.current = instance;
    const restore = async () => {
      if (kept.current.length) await api.restoreAlerts(kept.current).catch(() => undefined);
      await refresh();
    };
    void restore();
  }, [instance, refresh]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 8000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const remember = useCallback((cases: AlertCase[]) => {
    setNames((current) => {
      const next = { ...current };
      for (const c of cases) if (c.reference) next[c.ref] = c.reference;
      safeStorageSet(NAMES_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const value = useMemo<LedgerValue>(() => ({
    snapshot,
    cohort,
    names,
    remember,
    refresh: () => void refresh(),
    setCohort: (result) => {
      setCohortState(result);
      safeStorageSet(COHORT_KEY, JSON.stringify(result));
      remember(result.alerts);
      void refresh();
    },
    acknowledge: async (id, assignee, note) => {
      await api.acknowledge(id, assignee, note);
      await refresh();
    },
  }), [snapshot, cohort, names, remember, refresh]);

  return <Ledger.Provider value={value}>{children}</Ledger.Provider>;
}
