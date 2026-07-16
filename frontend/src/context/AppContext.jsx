import { createContext, useContext, useMemo } from "react";
import { API_BASE_URL } from "../api/api";

const AppContext = createContext(undefined);

const DEFAULT_REFRESH_INTERVAL_SECONDS = 5;

/**
 * Provides the small set of app-wide values every page needs:
 * the configured backend base URL and the live-data refresh
 * interval. Deliberately minimal - most state in this app is
 * page-local (fetched data, form selections) and lives in the page
 * component itself via `usePolling`/`useState`, not here. This
 * context exists purely to satisfy the "shared app configuration"
 * need without pulling in a state management library.
 *
 * @param {{children: React.ReactNode}} props
 */
export function AppProvider({ children }) {
  const value = useMemo(() => {
    const configuredSeconds = Number(import.meta.env.VITE_REFRESH_INTERVAL_SECONDS);
    const refreshIntervalSeconds =
      Number.isFinite(configuredSeconds) && configuredSeconds > 0
        ? configuredSeconds
        : DEFAULT_REFRESH_INTERVAL_SECONDS;

    return {
      apiBaseUrl: API_BASE_URL,
      refreshIntervalSeconds,
      refreshIntervalMs: refreshIntervalSeconds * 1000,
    };
  }, []);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

/**
 * Read the shared app context (backend base URL, refresh interval).
 *
 * @returns {{apiBaseUrl: string, refreshIntervalSeconds: number, refreshIntervalMs: number}}
 */
export function useAppContext() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error("useAppContext must be used within an AppProvider");
  }
  return context;
}
