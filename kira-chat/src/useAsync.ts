import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { kind: "loading"; data: null; error: null }
  | { kind: "ready"; data: T; error: null }
  | { kind: "error"; data: null; error: unknown };

const LOADING: AsyncState<unknown> = { kind: "loading", data: null, error: null };

/**
 * One implementation of "loading / empty / error" for every dashboard screen, because the
 * spec demands all three states be explicit on all of them. `deps` says when to re-read;
 * `refresh()` is how a screen re-reads after its own write.
 */
export function useAsync<T>(load: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> & { refresh(): void } {
  const [state, setState] = useState<AsyncState<T>>(LOADING as AsyncState<T>);
  const [epoch, setEpoch] = useState(0);
  const refresh = useCallback(() => setEpoch((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState(LOADING as AsyncState<T>);
    load().then(
      (data) => {
        if (!cancelled) setState({ kind: "ready", data, error: null });
      },
      (error) => {
        // A rejected read is state, not a swallowed exception: the screen shows it.
        if (!cancelled) setState({ kind: "error", data: null, error });
      },
    );
    return () => {
      cancelled = true;
    };
    // `load` is deliberately not a dependency: every caller passes a fresh closure, and
    // depending on it would re-fetch on every render. `deps` + `epoch` are the triggers.
  }, [...deps, epoch]);

  return { ...state, refresh };
}
