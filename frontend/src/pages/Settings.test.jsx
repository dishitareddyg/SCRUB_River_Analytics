import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/testUtils";
import Settings from "./Settings";
import * as sensorService from "../services/sensorService";

vi.mock("../services/sensorService");

const INFO = {
  application_name: "River Intelligence Platform",
  application_version: "0.1.0",
  environment: "development",
  connected_device: "river-bot-01",
  firmware_version: "1.2.0",
  configured_sensors: [
    { sensor_name: "dissolved_oxygen", display_name: "Dissolved Oxygen", unit: "mg/L", enabled: true },
  ],
  database_type: "postgresql",
};

describe("Settings page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders backend URL, application info, and the configured sensors table", async () => {
    sensorService.getSystemInfo.mockResolvedValue(INFO);

    renderWithProviders(<Settings />);

    expect(screen.getByText("Backend URL")).toBeInTheDocument();
    expect(screen.getByText("http://localhost:8000")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("0.1.0")).toBeInTheDocument());
    expect(screen.getByText("river-bot-01")).toBeInTheDocument();
    expect(screen.getByText("dissolved_oxygen")).toBeInTheDocument();
  });

  it("shows the dashboard-configured sampling interval with an explanatory tooltip", async () => {
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    renderWithProviders(<Settings />);
    expect(screen.getByText(/5s \(dashboard refresh\)/)).toBeInTheDocument();
  });

  it("shows an error card when system info cannot be loaded", async () => {
    sensorService.getSystemInfo.mockRejectedValue({
      kind: "network",
      status: null,
      message: "Could not reach the backend API.",
    });

    renderWithProviders(<Settings />);

    await waitFor(() => expect(screen.getByText("Backend Offline")).toBeInTheDocument());
  });
});
