import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import StatusCard from "./StatusCard";

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

describe("StatusCard", () => {
  it("renders a status chip when a status prop is given", () => {
    renderWithTheme(<StatusCard label="Database Status" status="ok" />);
    expect(screen.getByText("Database Status")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("renders a plain value instead of a chip when value is given", () => {
    renderWithTheme(<StatusCard label="Connected Device" value="river-bot-01" />);
    expect(screen.getByText("river-bot-01")).toBeInTheDocument();
  });

  it("falls back to an em dash when value is missing", () => {
    renderWithTheme(<StatusCard label="Connected Device" value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders helper text when provided", () => {
    renderWithTheme(<StatusCard label="Last Update" value="10:00" helperText="5s ago" />);
    expect(screen.getByText("5s ago")).toBeInTheDocument();
  });
});
