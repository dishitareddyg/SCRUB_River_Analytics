import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import TrendChart from "./TrendChart";

vi.mock("./LineChart", () => ({
  default: () => <div data-testid="mock-trend-chart" />,
}));

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const POINTS = [
  { timestamp: "2026-07-14T00:00:00Z", value: 6.0 },
  { timestamp: "2026-07-14T01:00:00Z", value: 8.0 },
  { timestamp: "2026-07-14T02:00:00Z", value: 10.0 },
];

describe("TrendChart", () => {
  it("computes and displays minimum, maximum, average, and latest", () => {
    renderWithTheme(<TrendChart points={POINTS} sensorLabel="Dissolved Oxygen" unit="mg/L" />);
    expect(within(screen.getByTestId("metric-card-Minimum")).getByText("6.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("metric-card-Maximum")).getByText("10.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("metric-card-Average")).getByText("8.00")).toBeInTheDocument();
    expect(within(screen.getByTestId("metric-card-Latest")).getByText("10.00")).toBeInTheDocument();
  });

  it("renders the chart when points are present", () => {
    renderWithTheme(<TrendChart points={POINTS} sensorLabel="Dissolved Oxygen" unit="mg/L" />);
    expect(screen.getByTestId("mock-trend-chart")).toBeInTheDocument();
  });

  it("ignores null values when computing stats", () => {
    const withNulls = [...POINTS, { timestamp: "2026-07-14T03:00:00Z", value: null }];
    renderWithTheme(<TrendChart points={withNulls} sensorLabel="Dissolved Oxygen" unit="mg/L" />);
    expect(screen.getByText("4 readings shown.", { exact: false })).toBeInTheDocument();
  });

  it("shows a no-data error card when there are no points", () => {
    renderWithTheme(<TrendChart points={[]} sensorLabel="Dissolved Oxygen" unit="mg/L" />);
    expect(screen.getByText("No Sensor Data")).toBeInTheDocument();
  });
});
