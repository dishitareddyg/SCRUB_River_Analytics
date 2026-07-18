import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/testUtils";
import Prediction from "./Prediction";
import * as sensorService from "../services/sensorService";

vi.mock("../services/sensorService");

const INFO = {
  application_name: "River Intelligence Platform",
  application_version: "0.1.0",
  environment: "development",
  connected_device: "river-bot-01",
  firmware_version: null,
  configured_sensors: [],
  database_type: "postgresql",
};

const PREDICTION = {
  status: "ok",
  parameter: "dissolved_oxygen",
  display_name: "Dissolved Oxygen",
  unit: "mg/L",
  horizon: "next_day",
  current_value: 7.5,
  predicted_value: 7.8,
  confidence_interval_lower: 7.0,
  confidence_interval_upper: 8.6,
  model_confidence: 0.75,
  model: { model_name: "trend_dissolved_oxygen_next_day", version: "v1", algorithm: "random_forest" },
};

const ANOMALY = {
  status: "ok",
  anomaly_score: 0.2,
  is_anomaly: false,
  confidence: 0.8,
  contributing_parameters: [],
};

const POLLUTION = {
  status: "ok",
  probabilities: { domestic_sewage: 0.2, natural_variation: 0.6, unknown: 0.2 },
  most_likely_source: "natural_variation",
  notes: [],
};

const RIVER_HEALTH = {
  status: "ok",
  current_score: 80,
  predicted_score: 78,
  health_category: "good",
  confidence: 0.7,
};

const HISTORY = {
  sensor_name: "dissolved_oxygen",
  display_name: "Dissolved Oxygen",
  unit: "mg/L",
  points: [{ timestamp: "2026-07-14T09:00:00Z", value: 7.5, validation_status: "valid" }],
};

describe("Prediction page", () => {
  it("renders a forecast card per trend parameter", async () => {
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    sensorService.getMlPredictions.mockResolvedValue(PREDICTION);
    sensorService.getMlAnomalies.mockResolvedValue(ANOMALY);
    sensorService.getMlPollution.mockResolvedValue(POLLUTION);
    sensorService.getMlRiverHealth.mockResolvedValue(RIVER_HEALTH);
    sensorService.getSensorHistory.mockResolvedValue(HISTORY);

    renderWithProviders(<Prediction />);

    await waitFor(() => {
      expect(screen.getAllByTestId(/forecast-card-/).length).toBe(6);
    });
    expect(sensorService.getMlPredictions).toHaveBeenCalledWith(
      "dissolved_oxygen",
      expect.objectContaining({ horizon: "next_day" })
    );
  });

  it("renders the anomaly indicator, pollution probabilities, and river health forecast", async () => {
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    sensorService.getMlPredictions.mockResolvedValue(PREDICTION);
    sensorService.getMlAnomalies.mockResolvedValue(ANOMALY);
    sensorService.getMlPollution.mockResolvedValue(POLLUTION);
    sensorService.getMlRiverHealth.mockResolvedValue(RIVER_HEALTH);
    sensorService.getSensorHistory.mockResolvedValue(HISTORY);

    renderWithProviders(<Prediction />);

    await waitFor(() => {
      expect(screen.getByTestId("anomaly-indicator")).toBeInTheDocument();
      expect(screen.getByTestId("pollution-probabilities")).toBeInTheDocument();
      expect(screen.getByTestId("river-health-forecast")).toBeInTheDocument();
    });
  });

  it("re-fetches river health when the horizon changes", async () => {
    sensorService.getSystemInfo.mockResolvedValue(INFO);
    sensorService.getMlPredictions.mockResolvedValue(PREDICTION);
    sensorService.getMlAnomalies.mockResolvedValue(ANOMALY);
    sensorService.getMlPollution.mockResolvedValue(POLLUTION);
    sensorService.getMlRiverHealth.mockResolvedValue(RIVER_HEALTH);
    sensorService.getSensorHistory.mockResolvedValue(HISTORY);

    renderWithProviders(<Prediction />);

    await waitFor(() => {
      expect(sensorService.getMlRiverHealth).toHaveBeenCalledWith(
        expect.objectContaining({ horizon: "next_day" })
      );
    });

    await userEvent.click(screen.getByRole("button", { name: "Next Week" }));

    await waitFor(() => {
      expect(sensorService.getMlRiverHealth).toHaveBeenCalledWith(
        expect.objectContaining({ horizon: "next_week" })
      );
    });
  });
});
