import axios from "axios";

/**
 * Base URL of the FastAPI backend, e.g. "http://localhost:8000".
 * Configured via VITE_API_BASE_URL (see .env.example) so the same
 * build can point at different backends without a code change.
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/**
 * Path prefix for version 1 of the backend API. Must match the
 * backend's `API_V1_PREFIX` setting exactly - this frontend consumes
 * the existing REST API as-is and never assumes a different prefix.
 */
export const API_V1_PREFIX = "/api/v1";

/** Request timeout, in milliseconds, configured via VITE_API_TIMEOUT_MS. */
const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS) || 8000;

/**
 * Shared Axios instance every service module uses to talk to the
 * backend. Centralizing this here means base URL, timeout, and
 * default headers are configured exactly once.
 */
const api = axios.create({
  baseURL: `${API_BASE_URL}${API_V1_PREFIX}`,
  timeout: REQUEST_TIMEOUT_MS,
  headers: {
    Accept: "application/json",
  },
});

/**
 * Normalized error shape every service function throws on failure,
 * regardless of whether the backend was unreachable, returned a
 * non-2xx status, or the request never left the browser.
 *
 * @typedef {Object} ApiError
 * @property {"network"|"http"|"unknown"} kind - Broad failure category.
 * @property {number|null} status - HTTP status code, when available.
 * @property {string} message - Human readable summary.
 * @property {unknown} original - The original thrown error, for debugging.
 */

/**
 * Convert any error thrown by Axios into a normalized {@link ApiError}.
 *
 * @param {unknown} error - The error caught from an Axios call.
 * @returns {ApiError} A normalized, UI-friendly error description.
 */
export function normalizeApiError(error) {
  if (axios.isAxiosError(error)) {
    if (error.response) {
      // The backend responded with a non-2xx status. Its body follows
      // the standard ErrorResponse envelope (see app/utils/response.py):
      // { success: false, error: { type, message, context }, meta }.
      const backendMessage = error.response.data?.error?.message;
      return {
        kind: "http",
        status: error.response.status,
        message: backendMessage || `Request failed with status ${error.response.status}.`,
        original: error,
      };
    }
    // Request was made but no response was received (backend offline,
    // CORS failure, DNS failure, timeout, etc.).
    return {
      kind: "network",
      status: null,
      message: "Could not reach the backend API. Is it running?",
      original: error,
    };
  }
  return {
    kind: "unknown",
    status: null,
    message: error?.message || "An unexpected error occurred.",
    original: error,
  };
}

export default api;
