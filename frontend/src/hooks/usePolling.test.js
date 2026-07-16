import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { usePolling } from "./usePolling";

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches immediately on mount", async () => {
    const fetchFn = vi.fn().mockResolvedValue({ value: 1 });
    const { result } = renderHook(() => usePolling(fetchFn, null));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(result.current.data).toEqual({ value: 1 });
    expect(result.current.error).toBeNull();
  });

  it("polls again after the interval elapses", async () => {
    const fetchFn = vi.fn().mockResolvedValue({ value: 1 });
    renderHook(() => usePolling(fetchFn, 5000));

    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(1));

    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(2));
  });

  it("does not poll again when intervalMs is null", async () => {
    const fetchFn = vi.fn().mockResolvedValue({ value: 1 });
    renderHook(() => usePolling(fetchFn, null));

    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(1));

    await act(async () => {
      vi.advanceTimersByTime(60000);
    });
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("captures a rejected fetch as `error` without throwing", async () => {
    const fetchFn = vi.fn().mockRejectedValue({ kind: "network", message: "offline" });
    const { result } = renderHook(() => usePolling(fetchFn, null));

    await waitFor(() => expect(result.current.error).toEqual({ kind: "network", message: "offline" }));
    expect(result.current.loading).toBe(false);
  });

  it("refetches when refresh() is called", async () => {
    const fetchFn = vi.fn().mockResolvedValue({ value: 1 });
    const { result } = renderHook(() => usePolling(fetchFn, null));

    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.refresh();
    });

    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(2));
  });

  it("refetches when a dependency changes", async () => {
    const fetchFn = vi.fn().mockResolvedValue({ value: 1 });
    const { rerender } = renderHook(({ dep }) => usePolling(fetchFn, null, [dep]), {
      initialProps: { dep: "a" },
    });

    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(1));

    rerender({ dep: "b" });

    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(2));
  });
});
