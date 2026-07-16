import api, { normalizeApiError } from "../api/api";

/**
 * Thin wrapper around every backend endpoint this dashboard consumes.
 *
 * Every exported function:
 *   - Issues exactly one GET request to an existing backend route
 *     (see app/api/routers/*.py on the backend - nothing here invents
 *     or renames an endpoint).
 *   - Unwraps the standard `SuccessResponse` envelope
 *     (`{ success, message, data, meta }`) and resolves with `data`
 *     only, since every caller only cares about the payload.
 *   - On failure, throws a normalized `ApiError` (see
 *     `src/api/api.js#normalizeApiError`) so every page can render a
 *     consistent error state regardless of failure mode.
 */

async function get(path, config) {
  try {
    const response = await api.get(path, config);
    return response.data.data;
  } catch (error) {
    throw normalizeApiError(error);
  }
}

/**
 * GET /system/health - application/database/serial status, version, uptime.
 * @returns {Promise<Object>} SystemHealthData payload.
 */
export function getSystemHealth() {
  return get("/system/health");
}

/**
 * GET /system/info - version, connected device, configured sensors, DB backend.
 * @returns {Promise<Object>} SystemInfoData payload.
 */
export function getSystemInfo() {
  return get("/system/info");
}

/**
 * GET /live/latest - the latest validated reading for every enabled sensor.
 * @param {Object} [params]
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @returns {Promise<Object>} LiveSensorsData payload.
 */
export function getLiveLatest({ deviceName } = {}) {
  return get("/live/latest", { params: deviceName ? { device_name: deviceName } : undefined });
}

/**
 * GET /analytics/latest - every registered derived parameter.
 * @param {Object} [params]
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @returns {Promise<Object>} AnalyticsLatestData payload.
 */
export function getAnalyticsLatest({ deviceName } = {}) {
  return get("/analytics/latest", { params: deviceName ? { device_name: deviceName } : undefined });
}

/**
 * GET /history/sensor/{sensorName} - paginated historical sensor readings.
 * @param {string} sensorName - Canonical sensor key (e.g. "dissolved_oxygen").
 * @param {Object} [params]
 * @param {"latest"|"hour"|"day"|"week"|"month"} [params.interval] - Convenience range shortcut.
 * @param {string} [params.start] - ISO 8601 range start (mutually exclusive with interval).
 * @param {string} [params.end] - ISO 8601 range end (mutually exclusive with interval).
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @param {number} [params.page] - 1-indexed page number.
 * @param {number} [params.pageSize] - Maximum records per page.
 * @returns {Promise<Object>} SensorHistoryData payload.
 */
export function getSensorHistory(
  sensorName,
  { interval, start, end, deviceName, page, pageSize } = {}
) {
  return get(`/history/sensor/${encodeURIComponent(sensorName)}`, {
    params: {
      interval,
      start,
      end,
      device_name: deviceName,
      page,
      page_size: pageSize,
    },
  });
}

/**
 * GET /history/analytics/{parameter} - historical series for one derived parameter.
 * @param {string} parameter - Registered analytics parameter key (e.g. "tds").
 * @param {Object} [params]
 * @param {"latest"|"hour"|"day"|"week"|"month"} [params.interval] - Convenience range shortcut.
 * @param {string} [params.start] - ISO 8601 range start (mutually exclusive with interval).
 * @param {string} [params.end] - ISO 8601 range end (mutually exclusive with interval).
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @param {number} [params.page] - 1-indexed page number.
 * @param {number} [params.pageSize] - Maximum points per page.
 * @returns {Promise<Object>} AnalyticsHistoryData payload.
 */
export function getAnalyticsHistory(
  parameter,
  { interval, start, end, deviceName, page, pageSize } = {}
) {
  return get(`/history/analytics/${encodeURIComponent(parameter)}`, {
    params: {
      interval,
      start,
      end,
      device_name: deviceName,
      page,
      page_size: pageSize,
    },
  });
}

/**
 * GET /history/statistics/{parameter} - historical summary statistics
 * (min/max/average/median/std-dev/variance/first/last/percent-change)
 * for a sensor or derived analytics parameter over a time window.
 * @param {string} parameter - Sensor key or analytics parameter key (e.g. "tds").
 * @param {Object} [params]
 * @param {"hour"|"day"|"week"|"month"|"quarter"|"year"} [params.window] - Convenience window shortcut.
 * @param {string} [params.start] - ISO 8601 custom range start (mutually exclusive with window).
 * @param {string} [params.end] - ISO 8601 custom range end (mutually exclusive with window).
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @returns {Promise<Object>} StatisticsData payload.
 */
export function getHistoricalStatistics(parameter, { window, start, end, deviceName } = {}) {
  return get(`/history/statistics/${encodeURIComponent(parameter)}`, {
    params: { window, start, end, device_name: deviceName },
  });
}

/**
 * GET /history/trends/{parameter} - trend direction, percent change,
 * rate of change, and fit confidence for a sensor or derived
 * analytics parameter over a time window.
 * @param {string} parameter - Sensor key or analytics parameter key.
 * @param {Object} [params]
 * @param {"hour"|"day"|"week"|"month"|"quarter"|"year"} [params.window] - Convenience window shortcut.
 * @param {string} [params.start] - ISO 8601 custom range start.
 * @param {string} [params.end] - ISO 8601 custom range end.
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @returns {Promise<Object>} TrendData payload.
 */
export function getHistoricalTrends(parameter, { window, start, end, deviceName } = {}) {
  return get(`/history/trends/${encodeURIComponent(parameter)}`, {
    params: { window, start, end, device_name: deviceName },
  });
}

/**
 * GET /history/seasonal/{parameter} - grouped summaries by a calendar
 * dimension (hour/day/week/month/season/year).
 * @param {string} parameter - Sensor key or analytics parameter key.
 * @param {Object} [params]
 * @param {"hour"|"day"|"week"|"month"|"season"|"year"} [params.groupBy] - Calendar dimension to group by.
 * @param {"hour"|"day"|"week"|"month"|"quarter"|"year"} [params.window] - Convenience window shortcut.
 * @param {string} [params.start] - ISO 8601 custom range start.
 * @param {string} [params.end] - ISO 8601 custom range end.
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @returns {Promise<Object>} SeasonalData payload.
 */
export function getHistoricalSeasonal(parameter, { groupBy, window, start, end, deviceName } = {}) {
  return get(`/history/seasonal/${encodeURIComponent(parameter)}`, {
    params: { group_by: groupBy, window, start, end, device_name: deviceName },
  });
}

/**
 * GET /history/compare - compares two sensors and/or derived
 * analytics parameters over the same time window, including their
 * Pearson correlation coefficient.
 * @param {string} parameterA - First parameter's sensor or analytics key.
 * @param {string} parameterB - Second parameter's sensor or analytics key.
 * @param {Object} [params]
 * @param {"hour"|"day"|"week"|"month"|"quarter"|"year"} [params.window] - Convenience window shortcut.
 * @param {string} [params.start] - ISO 8601 custom range start.
 * @param {string} [params.end] - ISO 8601 custom range end.
 * @param {string} [params.deviceName] - Restrict to a single device.
 * @returns {Promise<Object>} ComparisonData payload.
 */
export function getHistoricalComparison(parameterA, parameterB, { window, start, end, deviceName } = {}) {
  return get("/history/compare", {
    params: {
      parameter_a: parameterA,
      parameter_b: parameterB,
      window,
      start,
      end,
      device_name: deviceName,
    },
  });
}
