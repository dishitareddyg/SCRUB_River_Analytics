import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders } from "../test/testUtils";
import MainLayout from "./MainLayout";

function Stub({ text }) {
  return <div>{text}</div>;
}

function renderLayout(route = "/") {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Stub text="Dashboard Page" />} />
        <Route path="trends" element={<Stub text="Trends Page" />} />
        <Route path="analytics" element={<Stub text="Analytics Page" />} />
        <Route path="settings" element={<Stub text="Settings Page" />} />
      </Route>
    </Routes>,
    { route }
  );
}

describe("MainLayout", () => {
  it("renders all four sidebar navigation items", () => {
    renderLayout();
    expect(screen.getAllByText("Dashboard").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Trends").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Analytics").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Settings").length).toBeGreaterThan(0);
  });

  it("renders the routed page content", () => {
    renderLayout();
    expect(screen.getByText("Dashboard Page")).toBeInTheDocument();
  });

  it("navigates to Trends when the Trends nav item is clicked", async () => {
    renderLayout();
    const trendsButtons = screen.getAllByText("Trends");
    await userEvent.click(trendsButtons[0]);
    expect(screen.getByText("Trends Page")).toBeInTheDocument();
  });
});
