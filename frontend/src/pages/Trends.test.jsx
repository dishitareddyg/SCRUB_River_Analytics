import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/testUtils";
import Trends from "./Trends";
import * as sensorService from "../services/sensorService";

vi.mock("../services/sensorService");

const INFO = {
  application_name: "River Intelligence Platform",
  application_version: "0.1.0",
  environment: "development",
  connected_device: null,
  firmware_version: null,
  configured_sensors: [
    { sensor_name: "dissolved_oxygen", display_name: "Dissolved Oxygen", unit: "mg/L", enabled: true },
    { sensor_name: "conductivity", display_name: "Electrical Conductivity", unit: "uS/cm", enabled: false },
  ],
  database_type: "postgresql",
};

const HISTORY = {
  sensor_name: "dissolved_oxygen",
  display_name: "Dissolved Oxygen",
  unit: "mg/L",
  device_name: null,
  start: "2026-07-13T09:30:00Z",
  end: "2026-07-14T09:30:00Z",
  page: 1,
  page_size: 2000,
  total: 2,
  total_pages: 1,
  points: [
    { timestamp: "2026-07-14T08:00:00Z", value: 7.5, validation_status: "valid" },
    { timestamp: "2026-07-14T09:00:00Z", value: 8.0, validation_status: "valid" },
  ],
};

describe("Trends page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the sensor list, then fetches and renders history for the default sensor", async () => {
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    sensorService.getSensorHistory.mockResolvedValue(HISTORY);

    renderWithProviders(<Trends />);

    await waitFor(() =>
      expect(sensorService.getSensorHistory).toHaveBeenCalledWith("dissolved_oxygen", {
        interval: "day",
        pageSize: 2000,
      })
    );

    await waitFor(() =>
      expect(within(screen.getByTestId("metric-card-Latest")).getByText("8.00")).toBeInTheDocument()
    ); // latest
  });

  it("refetches when the time range changes", async () => {
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    sensorService.getSensorHistory.mockResolvedValue(HISTORY);

    renderWithProviders(<Trends />);
    await waitFor(() => expect(sensorService.getSensorHistory).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: "Last Hour" }));

    await waitFor(() =>
      expect(sensorService.getSensorHistory).toHaveBeenCalledWith(
        "dissolved_oxygen",
        expect.objectContaining({ interval: "hour" })
      )
    );
  });

  it("shows a no-data card when the backend has no configured sensors", async () => {
    sensorService.getSystemInfo.mockResolvedValue({ ...INFO, configured_sensors: [] });

    renderWithProviders(<Trends />);

    await waitFor(() => expect(screen.getByText("No Sensor Data")).toBeInTheDocument());
  });
});
