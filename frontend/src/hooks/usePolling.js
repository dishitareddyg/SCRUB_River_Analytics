import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Poll an async fetch function on an interval, exposing its latest
 * result, loading/error state, and a manual `refresh()` trigger.
 *
 * Used by the Live Dashboard and Analytics pages (5-second refresh)
 * per the project's refresh strategy - Trends fetches on-demand
 * instead and does not use this hook's interval behavior (call with
 * `intervalMs: null` to fetch once without polling).
 *
 * @param {() => Promise<any>} fetchFn - Called on mount and every
 *   `intervalMs`. Must be stable across renders (e.g. wrapped in
 *   `useCallback`) or passed inline - it is re-read on every poll via
 *   a ref, so it does not need to be memoized by the caller.
 * @param {number|null} intervalMs - Polling interval in milliseconds,
 *   or `null`/`0` to fetch only once (and on manual `refresh()` calls).
 * @param {Array} [deps] - When any value in this array changes, the
 *   poll loop resets and fetches immediately.
 * @returns {{data: any, error: import('../api/api').ApiError|null, loading: boolean, refresh: () => void}}
 */
export function usePolling(fetchFn, intervalMs, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  const isMountedRef = useRef(true);
  const [refreshToken, setRefreshToken] = useState(0);

  const refresh = useCallback(() => setRefreshToken((token) => token + 1), []);

  useEffect(() => {
    isMountedRef.current = true;
    let timerId;

    const run = async () => {
      try {
        const result = await fetchFnRef.current();
        if (!isMountedRef.current) return;
        setData(result);
        setError(null);
      } catch (err) {
        if (!isMountedRef.current) return;
        setError(err);
      } finally {
        if (isMountedRef.current) setLoading(false);
      }
    };

    setLoading(true);
    run();

    if (intervalMs) {
      timerId = setInterval(run, intervalMs);
    }

    return () => {
      isMountedRef.current = false;
      if (timerId) clearInterval(timerId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, refreshToken, ...deps]);

  return { data, error, loading, refresh };
}
