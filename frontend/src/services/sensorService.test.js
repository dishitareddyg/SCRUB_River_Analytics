import { describe, it, expect, vi, beforeEach } from "vitest";
import api from "../api/api";
import {
  getSystemHealth,
  getSystemInfo,
  getLiveLatest,
  getAnalyticsLatest,
  getSensorHistory,
  getAnalyticsHistory,
  getHistoricalStatistics,
  getHistoricalTrends,
  getHistoricalSeasonal,
  getHistoricalComparison,
} from "./sensorService";

vi.mock("../api/api", async () => {
  const actual = await vi.importActual("../api/api");
  return {
    ...actual,
    default: { get: vi.fn() },
  };
});

function mockSuccess(data) {
  api.get.mockResolvedValueOnce({ data: { success: true, message: "ok", data } });
}

describe("sensorService", () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it("getSystemHealth calls GET /system/health and unwraps data", async () => {
    mockSuccess({ application_status: "ok" });
    const result = await getSystemHealth();
    expect(api.get).toHaveBeenCalledWith("/system/health", undefined);
    expect(result).toEqual({ application_status: "ok" });
  });

  it("getSystemInfo calls GET /system/info", async () => {
    mockSuccess({ application_version: "0.1.0" });
    await getSystemInfo();
    expect(api.get).toHaveBeenCalledWith("/system/info", undefined);
  });

  it("getLiveLatest calls GET /live/latest without device filter by default", async () => {
    mockSuccess({ readings: [] });
    await getLiveLatest();
    expect(api.get).toHaveBeenCalledWith("/live/latest", { params: undefined });
  });

  it("getLiveLatest passes device_name when provided", async () => {
    mockSuccess({ readings: [] });
    await getLiveLatest({ deviceName: "river-bot-01" });
    expect(api.get).toHaveBeenCalledWith("/live/latest", { params: { device_name: "river-bot-01" } });
  });

  it("getAnalyticsLatest calls GET /analytics/latest", async () => {
    mockSuccess({ results: [] });
    await getAnalyticsLatest();
    expect(api.get).toHaveBeenCalledWith("/analytics/latest", { params: undefined });
  });

  it("getSensorHistory calls GET /history/sensor/{name} with query params", async () => {
    mockSuccess({ points: [] });
    await getSensorHistory("dissolved_oxygen", { interval: "day", page: 1, pageSize: 100 });
    expect(api.get).toHaveBeenCalledWith("/history/sensor/dissolved_oxygen", {
      params: {
        interval: "day",
        start: undefined,
        end: undefined,
        device_name: undefined,
        page: 1,
        page_size: 100,
      },
    });
  });

  it("getAnalyticsHistory calls GET /history/analytics/{parameter} with query params", async () => {
    mockSuccess({ points: [] });
    await getAnalyticsHistory("tds", { interval: "week" });
    expect(api.get).toHaveBeenCalledWith("/history/analytics/tds", {
      params: {
        interval: "week",
        start: undefined,
        end: undefined,
        device_name: undefined,
        page: undefined,
        page_size: undefined,
      },
    });
  });

  it("getHistoricalStatistics calls GET /history/statistics/{parameter} with query params", async () => {
    mockSuccess({ parameter: "tds" });
    await getHistoricalStatistics("tds", { window: "week" });
    expect(api.get).toHaveBeenCalledWith("/history/statistics/tds", {
      params: { window: "week", start: undefined, end: undefined, device_name: undefined },
    });
  });

  it("getHistoricalTrends calls GET /history/trends/{parameter} with query params", async () => {
    mockSuccess({ direction: "stable" });
    await getHistoricalTrends("dissolved_oxygen", { start: "2026-01-01", end: "2026-01-02" });
    expect(api.get).toHaveBeenCalledWith("/history/trends/dissolved_oxygen", {
      params: { window: undefined, start: "2026-01-01", end: "2026-01-02", device_name: undefined },
    });
  });

  it("getHistoricalSeasonal calls GET /history/seasonal/{parameter} with query params", async () => {
    mockSuccess({ groups: [] });
    await getHistoricalSeasonal("dissolved_oxygen", { groupBy: "month", window: "year" });
    expect(api.get).toHaveBeenCalledWith("/history/seasonal/dissolved_oxygen", {
      params: { group_by: "month", window: "year", start: undefined, end: undefined, device_name: undefined },
    });
  });

  it("getHistoricalComparison calls GET /history/compare with both parameter keys", async () => {
    mockSuccess({ correlation: 0.5 });
    await getHistoricalComparison("dissolved_oxygen", "water_temperature", { window: "day" });
    expect(api.get).toHaveBeenCalledWith("/history/compare", {
      params: {
        parameter_a: "dissolved_oxygen",
        parameter_b: "water_temperature",
        window: "day",
        start: undefined,
        end: undefined,
        device_name: undefined,
      },
    });
  });

  it("throws a normalized ApiError when the request fails", async () => {
    api.get.mockRejectedValueOnce(new Error("network down"));
    await expect(getSystemHealth()).rejects.toMatchObject({ kind: "unknown" });
  });
});
