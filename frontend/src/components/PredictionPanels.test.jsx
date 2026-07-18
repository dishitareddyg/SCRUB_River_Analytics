import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import ForecastCard from "./ForecastCard";
import AnomalyIndicator from "./AnomalyIndicator";
import PollutionSourceProbabilities from "./PollutionSourceProbabilities";
import RiverHealthForecastCard from "./RiverHealthForecastCard";

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

describe("ForecastCard", () => {
  it("renders the predicted value, current value, and confidence", () => {
    renderWithTheme(
      <ForecastCard
        parameter="dissolved_oxygen"
        prediction={{
          status: "ok",
          display_name: "Dissolved Oxygen",
          unit: "mg/L",
          current_value: 7.5,
          predicted_value: 8.0,
          confidence_interval_lower: 7.2,
          confidence_interval_upper: 8.8,
          model_confidence: 0.82,
        }}
      />
    );
    expect(screen.getByText("Dissolved Oxygen")).toBeInTheDocument();
    expect(screen.getByText("8.00")).toBeInTheDocument();
    expect(screen.getByText(/82% confidence/)).toBeInTheDocument();
  });

  it("shows an insufficient-data message when status is insufficient_data", () => {
    renderWithTheme(<ForecastCard parameter="dissolved_oxygen" prediction={{ status: "insufficient_data" }} />);
    expect(screen.getByText(/Not enough historical data/)).toBeInTheDocument();
  });

  it("falls back to the parameter key while loading", () => {
    renderWithTheme(<ForecastCard parameter="dissolved_oxygen" prediction={null} />);
    expect(screen.getByText("dissolved_oxygen")).toBeInTheDocument();
  });
});

describe("AnomalyIndicator", () => {
  it("shows Normal for a non-anomalous reading", () => {
    renderWithTheme(
      <AnomalyIndicator
        anomaly={{ status: "ok", anomaly_score: 0.1, is_anomaly: false, confidence: 0.9, contributing_parameters: [] }}
      />
    );
    expect(screen.getByText("Normal")).toBeInTheDocument();
  });

  it("shows Anomaly Detected and contributing parameters", () => {
    renderWithTheme(
      <AnomalyIndicator
        anomaly={{
          status: "ok",
          anomaly_score: 0.85,
          is_anomaly: true,
          confidence: 0.7,
          contributing_parameters: ["conductivity"],
        }}
      />
    );
    expect(screen.getByText("Anomaly Detected")).toBeInTheDocument();
    expect(screen.getByText("conductivity")).toBeInTheDocument();
  });

  it("shows insufficient-data message", () => {
    renderWithTheme(<AnomalyIndicator anomaly={{ status: "insufficient_data" }} />);
    expect(screen.getByText(/Not enough historical data/)).toBeInTheDocument();
  });
});

describe("PollutionSourceProbabilities", () => {
  it("renders every source with its percentage, most likely first", () => {
    renderWithTheme(
      <PollutionSourceProbabilities
        pollution={{
          status: "ok",
          probabilities: {
            domestic_sewage: 0.5,
            agricultural_runoff: 0.2,
            industrial_effluent: 0.1,
            stormwater: 0.1,
            natural_variation: 0.05,
            unknown: 0.05,
          },
          most_likely_source: "domestic_sewage",
          notes: ["domestic_sewage: DO dropping sharply"],
        }}
      />
    );
    expect(screen.getByText("Domestic Sewage")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("shows insufficient-data message", () => {
    renderWithTheme(<PollutionSourceProbabilities pollution={{ status: "insufficient_data" }} />);
    expect(screen.getByText(/Not enough sensor data/)).toBeInTheDocument();
  });
});

describe("RiverHealthForecastCard", () => {
  it("renders current score, predicted score, and category", () => {
    renderWithTheme(
      <RiverHealthForecastCard
        forecast={{
          status: "ok",
          current_score: 82,
          predicted_score: 78,
          health_category: "good",
          confidence: 0.65,
        }}
      />
    );
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText("78")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument();
  });

  it("shows insufficient-data message", () => {
    renderWithTheme(<RiverHealthForecastCard forecast={{ status: "insufficient_data" }} />);
    expect(screen.getByText(/Not enough historical data/)).toBeInTheDocument();
  });
});
