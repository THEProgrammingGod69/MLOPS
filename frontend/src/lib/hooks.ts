import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean; // first load only
  refreshing: boolean; // background refetch: previous data stays on screen
  reload: () => void;
}

/** Fetch with optional polling. Keeps the previous result while refetching (no skeleton flash). */
export function useApi<T>(fetcher: () => Promise<T>, intervalMs = 0, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const mounted = useRef(true);

  const run = useCallback(async (initial: boolean) => {
    if (!initial) setRefreshing(true);
    try {
      const result = await fetcherRef.current();
      if (!mounted.current) return;
      setData(result);
      setError(null);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    run(true);
    if (!intervalMs) return () => { mounted.current = false; };
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") run(false);
    }, intervalMs);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
    };
  }, [intervalMs, run, ...deps]);

  return { data, error, loading, refreshing, reload: () => run(false) };
}

/** Minimal hash router: "#/assess" -> "/assess". Works under any base path (FastAPI /ui, nginx, Vite). */
export function useHashRoute(): string {
  const read = () => window.location.hash.replace(/^#/, "") || "/";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => {
      setRoute(read());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function safeStorageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeStorageSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode / blocked storage: preference simply isn't remembered */
  }
}

export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
