import { useCallback, useEffect, useRef, useState } from "react";

export interface Loaded<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

/** Sent when a page changes the ledger or the policy, so that the sidebar shows the new state. */
export const STORE_CHANGED = "auditiq:store-changed";

export function notifyStoreChanged(): void {
  window.dispatchEvent(new Event(STORE_CHANGED));
}

/** Load data from the API when the component mounts or a dependency changes. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [round, setRound] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    loadRef
      .current()
      .then((value) => live && setData(value))
      .catch((err: unknown) => live && setError(err instanceof Error ? err : new Error(String(err))))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, round]);

  const reload = useCallback(() => setRound((n) => n + 1), []);
  return { data, error, loading, reload };
}
