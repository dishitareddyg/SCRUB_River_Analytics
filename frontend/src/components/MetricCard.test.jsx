import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import MetricCard from "./MetricCard";

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

describe("MetricCard", () => {
  it("renders the label, value, and unit", () => {
    renderWithTheme(<MetricCard label="Minimum" value="6.42" unit="mg/L" />);
    expect(screen.getByText("Minimum")).toBeInTheDocument();
    expect(screen.getByText("6.42")).toBeInTheDocument();
    expect(screen.getByText("mg/L")).toBeInTheDocument();
  });

  it("renders without a unit", () => {
    renderWithTheme(<MetricCard label="Latest" value="8.10" />);
    expect(screen.getByText("8.10")).toBeInTheDocument();
  });
});
