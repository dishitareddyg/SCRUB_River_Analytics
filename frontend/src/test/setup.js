import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom does not implement ResizeObserver; LineChart.jsx uses it to
// auto-resize the chart. A minimal no-op stub is enough for tests.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom has no canvas/WebGL backend, so real ECharts rendering isn't
// possible (and isn't useful) in unit tests. Every test gets a
// lightweight, deterministic stub instead - tests assert that
// `echarts.init`/`setOption` were called with the right shape rather
// than inspecting pixels.
vi.mock("echarts", () => {
  const chartInstance = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  };
  return {
    init: vi.fn(() => chartInstance),
  };
});
