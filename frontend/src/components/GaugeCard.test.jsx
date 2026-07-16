import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import GaugeCard from "./GaugeCard";

vi.mock("./LineChart", () => ({
  default: ({ ariaLabel }) => <div data-testid="mock-gauge-chart">{ariaLabel}</div>,
}));

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const BASE_READING = {
  sensor_name: "dissolved_oxygen",
  display_name: "Dissolved Oxygen",
  value: 8.42,
  unit: "mg/L",
  timestamp: "2026-07-14T09:30:00Z",
  quality_status: "good",
  validation_status: "valid",
};

describe("GaugeCard", () => {
  it("renders the sensor display name, unit, and quality chip", () => {
    renderWithTheme(<GaugeCard reading={BASE_READING} />);
    expect(screen.getByText("Dissolved Oxygen")).toBeInTheDocument();
    expect(screen.getByText("mg/L")).toBeInTheDocument();
    expect(screen.getByText("good")).toBeInTheDocument();
  });

  it("passes an aria-label describing the gauge to the chart", () => {
    renderWithTheme(<GaugeCard reading={BASE_READING} />);
    expect(screen.getByText("Dissolved Oxygen gauge")).toBeInTheDocument();
  });

  it("renders a no_data quality chip for sensors with no reading yet", () => {
    renderWithTheme(
      <GaugeCard
        reading={{
          sensor_name: "conductivity",
          display_name: "Electrical Conductivity",
          value: null,
          unit: "uS/cm",
          timestamp: null,
          quality_status: "no_data",
          validation_status: "no_data",
        }}
      />
    );
    expect(screen.getByText("no data")).toBeInTheDocument();
  });

  it("renders an out_of_range quality chip", () => {
    renderWithTheme(<GaugeCard reading={{ ...BASE_READING, quality_status: "out_of_range" }} />);
    expect(screen.getByText("out of range")).toBeInTheDocument();
  });
});
