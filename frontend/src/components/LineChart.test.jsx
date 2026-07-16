import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import * as echarts from "echarts";
import LineChart from "./LineChart";

describe("LineChart", () => {
  it("initializes an ECharts instance on mount", () => {
    render(<LineChart option={{ series: [] }} />);
    expect(echarts.init).toHaveBeenCalledTimes(1);
  });

  it("calls setOption with the provided option", () => {
    const option = { series: [{ type: "line", data: [1, 2, 3] }] };
    render(<LineChart option={option} />);
    const instance = echarts.init.mock.results[0].value;
    expect(instance.setOption).toHaveBeenCalledWith(option, { notMerge: true, lazyUpdate: true });
  });

  it("disposes the chart instance on unmount", () => {
    const { unmount } = render(<LineChart option={{ series: [] }} />);
    const instance = echarts.init.mock.results[0].value;
    unmount();
    expect(instance.dispose).toHaveBeenCalledTimes(1);
  });

  it("renders a region with the given aria label", () => {
    const { getByRole } = render(<LineChart option={{ series: [] }} ariaLabel="TDS trend chart" />);
    expect(getByRole("img", { name: "TDS trend chart" })).toBeInTheDocument();
  });
});
