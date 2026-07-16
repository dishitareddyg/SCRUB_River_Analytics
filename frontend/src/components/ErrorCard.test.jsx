import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../theme/theme";
import ErrorCard, { variantFromApiError } from "./ErrorCard";

function renderWithTheme(ui) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

describe("ErrorCard", () => {
  it("renders the Backend Offline variant", () => {
    renderWithTheme(<ErrorCard variant="backend-offline" />);
    expect(screen.getByText("Backend Offline")).toBeInTheDocument();
  });

  it("renders the Database Offline variant", () => {
    renderWithTheme(<ErrorCard variant="database-offline" />);
    expect(screen.getByText("Database Offline")).toBeInTheDocument();
  });

  it("renders the Serial Disconnected variant", () => {
    renderWithTheme(<ErrorCard variant="serial-disconnected" />);
    expect(screen.getByText("Serial Disconnected")).toBeInTheDocument();
  });

  it("renders the No Sensor Data variant", () => {
    renderWithTheme(<ErrorCard variant="no-data" />);
    expect(screen.getByText("No Sensor Data")).toBeInTheDocument();
  });

  it("falls back to the generic variant for an unknown key", () => {
    renderWithTheme(<ErrorCard variant="not-a-real-variant" />);
    expect(screen.getByText("Something Went Wrong")).toBeInTheDocument();
  });

  it("renders optional detail text", () => {
    renderWithTheme(<ErrorCard variant="generic" detail="Connection refused" />);
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
  });

  it("calls onRetry when the Retry button is clicked", async () => {
    const onRetry = vi.fn();
    renderWithTheme(<ErrorCard variant="backend-offline" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not render a Retry button when onRetry is not provided", () => {
    renderWithTheme(<ErrorCard variant="backend-offline" />);
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });
});

describe("variantFromApiError", () => {
  it("maps a network error to backend-offline", () => {
    expect(variantFromApiError({ kind: "network" })).toBe("backend-offline");
  });

  it("maps a 404 to no-data", () => {
    expect(variantFromApiError({ kind: "http", status: 404 })).toBe("no-data");
  });

  it("maps other http errors to generic", () => {
    expect(variantFromApiError({ kind: "http", status: 500 })).toBe("generic");
  });

  it("maps a null error to generic", () => {
    expect(variantFromApiError(null)).toBe("generic");
  });
});
