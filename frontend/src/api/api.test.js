import { describe, it, expect } from "vitest";
import { AxiosError } from "axios";
import { normalizeApiError } from "./api";

describe("normalizeApiError", () => {
  it("normalizes an HTTP error response using the backend's error envelope", () => {
    const error = new AxiosError("Request failed");
    error.response = {
      status: 404,
      data: { success: false, error: { type: "NotFoundError", message: "Unknown sensor 'foo'." } },
    };

    const result = normalizeApiError(error);

    expect(result.kind).toBe("http");
    expect(result.status).toBe(404);
    expect(result.message).toBe("Unknown sensor 'foo'.");
  });

  it("falls back to a generic message when the backend sends no error body", () => {
    const error = new AxiosError("Request failed");
    error.response = { status: 500, data: {} };

    const result = normalizeApiError(error);

    expect(result.status).toBe(500);
    expect(result.message).toContain("500");
  });

  it("normalizes a network error (no response received) as kind 'network'", () => {
    const error = new AxiosError("Network Error");
    // No `.response` set - simulates the backend being unreachable.

    const result = normalizeApiError(error);

    expect(result.kind).toBe("network");
    expect(result.status).toBeNull();
    expect(result.message).toMatch(/backend/i);
  });

  it("normalizes a non-Axios error as kind 'unknown'", () => {
    const result = normalizeApiError(new Error("boom"));
    expect(result.kind).toBe("unknown");
    expect(result.message).toBe("boom");
  });
});
