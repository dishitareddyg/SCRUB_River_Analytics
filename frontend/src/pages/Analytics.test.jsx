import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/testUtils";
import Analytics from "./Analytics";
import * as sensorService from "../services/sensorService";

vi.mock("../services/sensorService");

const ANALYTICS_LATEST = {
  device_name: null,
  results: [
    {
      parameter: "tds",
      display_name: "Total Dissolved Solids",
      status: "OK",
      value: 325.0,
      unit: "mg/L",
      timestamp: "2026-07-14T09:30:00Z",
      confidence: 0.8,
      formula_used: "Conductivity-to-TDS empirical conversion (Hem, 1985)",
      reference: "Hem, J.D. (1985), USGS Water-Supply Paper 2254.",
      missing_inputs: [],
      warnings: [],
      error_message: null,
    },
    {
      parameter: "river_width",
      display_name: "River Width",
      status: "NOT_COMPUTABLE",
      value: null,
      unit: "m",
      timestamp: "2026-07-14T09:30:00Z",
      confidence: null,
      formula_used: "Trapezoidal channel top width (Chow, 1959)",
      reference: "Chow, V.T. (1959).",
      missing_inputs: ["geometry.bed_width_m (site survey configuration)"],
      warnings: [],
      error_message: null,
    },
  ],
};

describe("Analytics page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a card for every returned parameter", async () => {
    sensorService.getAnalyticsLatest.mockResolvedValue(ANALYTICS_LATEST);

    renderWithProviders(<Analytics />);

    await waitFor(() => expect(screen.getByText("Total Dissolved Solids")).toBeInTheDocument());
    expect(screen.getByText("325.00")).toBeInTheDocument();
    expect(screen.getByText("River Width")).toBeInTheDocument();
  });

  it("shows missing inputs for a NOT_COMPUTABLE parameter", async () => {
    sensorService.getAnalyticsLatest.mockResolvedValue(ANALYTICS_LATEST);

    renderWithProviders(<Analytics />);

    await waitFor(() =>
      expect(screen.getByText(/geometry.bed_width_m/i)).toBeInTheDocument()
    );
  });

  it("shows a backend-offline error card when the request fails", async () => {
    sensorService.getAnalyticsLatest.mockRejectedValue({
      kind: "network",
      status: null,
      message: "Could not reach the backend API.",
    });

    renderWithProviders(<Analytics />);

    await waitFor(() => expect(screen.getByText("Backend Offline")).toBeInTheDocument());
  });
});
