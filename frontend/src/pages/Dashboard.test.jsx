import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/testUtils";
import Dashboard from "./Dashboard";
import * as sensorService from "../services/sensorService";

vi.mock("../services/sensorService");

const HEALTH = {
  application_status: "ok",
  database_status: "ok",
  serial_connection_status: "disconnected",
  version: "0.1.0",
  uptime_seconds: 42,
};

const INFO = {
  application_name: "River Intelligence Platform",
  application_version: "0.1.0",
  environment: "development",
  connected_device: "river-bot-01",
  firmware_version: "1.2.0",
  configured_sensors: [],
  database_type: "postgresql",
};

const LIVE = {
  device_name: null,
  readings: [
    {
      sensor_name: "dissolved_oxygen",
      display_name: "Dissolved Oxygen",
      value: 8.42,
      unit: "mg/L",
      timestamp: "2026-07-14T09:30:00Z",
      quality_status: "good",
      validation_status: "valid",
    },
  ],
};

describe("Dashboard page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading state, then the status strip and gauges", async () => {
    sensorService.getSystemHealth.mockResolvedValue(HEALTH);
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    sensorService.getLiveLatest.mockResolvedValue(LIVE);

    renderWithProviders(<Dashboard />);

    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Dissolved Oxygen")).toBeInTheDocument());

    expect(screen.getByText("Database Status")).toBeInTheDocument();
    expect(screen.getByText("river-bot-01")).toBeInTheDocument();
  });

  it("shows a backend-offline error card when the API is unreachable", async () => {
    const networkError = { kind: "network", status: null, message: "Could not reach the backend API." };
    sensorService.getSystemHealth.mockRejectedValue(networkError);
    sensorService.getSystemInfo.mockRejectedValue(networkError);
    sensorService.getLiveLatest.mockRejectedValue(networkError);

    renderWithProviders(<Dashboard />);

    await waitFor(() => expect(screen.getByText("Backend Offline")).toBeInTheDocument());
  });

  it("shows a no-data card when no sensors are enabled", async () => {
    sensorService.getSystemHealth.mockResolvedValue(HEALTH);
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    sensorService.getLiveLatest.mockResolvedValue({ device_name: null, readings: [] });

    renderWithProviders(<Dashboard />);

    await waitFor(() => expect(screen.getByText("No Sensor Data")).toBeInTheDocument());
  });
});
