import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import SensorTable from "./SensorTable";

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const SENSORS = [
  { sensor_name: "dissolved_oxygen", display_name: "Dissolved Oxygen", unit: "mg/L", enabled: true },
  { sensor_name: "conductivity", display_name: "Electrical Conductivity", unit: "uS/cm", enabled: false },
];

describe("SensorTable", () => {
  it("renders one row per sensor", () => {
    renderWithTheme(<SensorTable sensors={SENSORS} />);
    expect(screen.getByText("dissolved_oxygen")).toBeInTheDocument();
    expect(screen.getByText("Dissolved Oxygen")).toBeInTheDocument();
    expect(screen.getByText("mg/L")).toBeInTheDocument();
    expect(screen.getByText("conductivity")).toBeInTheDocument();
  });

  it("shows Enabled/Disabled chips correctly", () => {
    renderWithTheme(<SensorTable sensors={SENSORS} />);
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });

  it("renders an empty state when there are no sensors", () => {
    renderWithTheme(<SensorTable sensors={[]} />);
    expect(screen.getByText(/no sensors are configured/i)).toBeInTheDocument();
  });
});
