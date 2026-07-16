import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import TrendIndicator from "./TrendIndicator";
import StatisticsPanel from "./StatisticsPanel";
import ComparisonPanel from "./ComparisonPanel";

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

describe("TrendIndicator", () => {
  it("renders an Increasing chip with percentage and confidence", () => {
    renderWithTheme(
      <TrendIndicator trend={{ direction: "increasing", trend_percentage: 12.5, trend_confidence: 0.9 }} />
    );
    expect(screen.getByText("Increasing")).toBeInTheDocument();
    expect(screen.getByText("12.5%")).toBeInTheDocument();
  });

  it("renders Insufficient Data when trend is null", () => {
    renderWithTheme(<TrendIndicator trend={null} />);
    expect(screen.getByText("Insufficient Data")).toBeInTheDocument();
  });

  it("renders a Rapid Decrease chip", () => {
    renderWithTheme(
      <TrendIndicator trend={{ direction: "rapid_decrease", trend_percentage: -30, trend_confidence: 0.8 }} />
    );
    expect(screen.getByText("Rapid Decrease")).toBeInTheDocument();
  });
});

describe("StatisticsPanel", () => {
  const statistics = {
    minimum: 1.0,
    maximum: 9.0,
    average: 5.0,
    median: 5.0,
    last_value: 8.0,
  };
  const trend = { direction: "stable", trend_percentage: 0.5, trend_confidence: 0.4 };

  it("renders a metric card for each statistic", () => {
    renderWithTheme(<StatisticsPanel statistics={statistics} trend={trend} unit="mg/L" />);
    expect(screen.getByTestId("metric-card-Minimum")).toHaveTextContent("1.00");
    expect(screen.getByTestId("metric-card-Maximum")).toHaveTextContent("9.00");
    expect(screen.getByTestId("metric-card-Average")).toHaveTextContent("5.00");
    expect(screen.getByTestId("metric-card-Median")).toHaveTextContent("5.00");
    expect(screen.getByTestId("metric-card-Latest Value")).toHaveTextContent("8.00");
    expect(screen.getByTestId("trend-indicator")).toHaveTextContent("Stable");
  });

  it("renders em dashes when statistics is null", () => {
    renderWithTheme(<StatisticsPanel statistics={null} trend={null} />);
    expect(screen.getByTestId("metric-card-Minimum")).toHaveTextContent("—");
  });
});

describe("ComparisonPanel", () => {
  it("renders nothing when comparison is null", () => {
    const { container } = renderWithTheme(<ComparisonPanel comparison={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders both parameters' names, averages, and correlation strength", () => {
    renderWithTheme(
      <ComparisonPanel
        comparison={{
          display_name_a: "Dissolved Oxygen",
          display_name_b: "Water Temperature",
          average_a: 7.5,
          average_b: 18.2,
          minimum_a: 5.0,
          maximum_a: 9.0,
          minimum_b: 15.0,
          maximum_b: 21.0,
          correlation: 0.85,
          matched_points: 24,
        }}
      />
    );
    expect(screen.getByText("Dissolved Oxygen vs Water Temperature")).toBeInTheDocument();
    expect(screen.getByText(/Strong Positive/)).toBeInTheDocument();
    expect(screen.getByText(/24 time-aligned sample pair/)).toBeInTheDocument();
  });

  it("shows a not-enough-data label when correlation is null", () => {
    renderWithTheme(
      <ComparisonPanel
        comparison={{
          display_name_a: "A",
          display_name_b: "B",
          average_a: null,
          average_b: null,
          minimum_a: null,
          maximum_a: null,
          minimum_b: null,
          maximum_b: null,
          correlation: null,
          matched_points: 0,
        }}
      />
    );
    expect(screen.getByText("Not enough overlapping data")).toBeInTheDocument();
  });
});
