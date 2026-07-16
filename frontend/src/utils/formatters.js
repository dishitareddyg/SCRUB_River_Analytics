/**
 * Format a numeric sensor/analytics value for display.
 *
 * @param {number|null|undefined} value
 * @param {number} [decimals=2] - Decimal places to round to.
 * @returns {string} A formatted number, or "—" when unavailable.
 */
export function formatValue(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return Number(value).toFixed(decimals);
}

/**
 * Format an ISO timestamp as a short, locale-aware date/time string.
 *
 * @param {string|null|undefined} isoTimestamp
 * @returns {string} A formatted timestamp, or "—" when unavailable.
 */
export function formatTimestamp(isoTimestamp) {
  if (!isoTimestamp) return "—";
  const date = new Date(isoTimestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * Format an ISO timestamp as a relative "time ago" string, refreshed
 * lazily (not tied to a ticking clock) - good enough for a badge that
 * re-renders on every 5-second poll anyway.
 *
 * @param {string|null|undefined} isoTimestamp
 * @returns {string} e.g. "3s ago", "2m ago", or "—" when unavailable.
 */
export function formatRelativeTime(isoTimestamp) {
  if (!isoTimestamp) return "—";
  const date = new Date(isoTimestamp);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

/**
 * Convert a snake_case identifier into Title Case, as a display-name
 * fallback for anything the backend doesn't already provide a
 * display_name for.
 *
 * @param {string} key
 * @returns {string}
 */
export function titleCaseFromKey(key) {
  if (!key) return "";
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
