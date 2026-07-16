import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import Box from "@mui/material/Box";

/**
 * A generic, responsive Apache ECharts container.
 *
 * Handles chart lifecycle only (init, option updates, resize,
 * dispose) - callers supply a complete ECharts `option` object, so
 * this component stays reusable for any chart type, not just line
 * charts.
 *
 * @param {Object} props
 * @param {Object} props.option - A full ECharts option object.
 * @param {number|string} [props.height=320] - Chart height.
 * @param {string} [props.ariaLabel] - Accessible label for the chart region.
 */
export default function LineChart({ option, height = 320, ariaLabel = "Chart" }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  // Init once.
  useEffect(() => {
    if (!containerRef.current) return undefined;

    const chart = echarts.init(containerRef.current, null, { renderer: "canvas" });
    chartRef.current = chart;

    const resizeObserver = new ResizeObserver(() => {
      chart.resize();
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // Apply option updates without re-initializing the chart instance.
  useEffect(() => {
    if (!chartRef.current || !option) return;
    chartRef.current.setOption(option, { notMerge: true, lazyUpdate: true });
  }, [option]);

  return (
    <Box
      ref={containerRef}
      role="img"
      aria-label={ariaLabel}
      sx={{ width: "100%", height }}
    />
  );
}
