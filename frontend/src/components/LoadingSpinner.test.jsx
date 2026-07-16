import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LoadingSpinner from "./LoadingSpinner";

describe("LoadingSpinner", () => {
  it("renders the default message and a status role", () => {
    render(<LoadingSpinner />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders a custom message", () => {
    render(<LoadingSpinner message="Connecting to backend..." />);
    expect(screen.getByText("Connecting to backend...")).toBeInTheDocument();
  });

  it("omits the message text when message is empty", () => {
    render(<LoadingSpinner message="" />);
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
  });
});
