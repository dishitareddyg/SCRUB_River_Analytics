import { useMemo } from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import LineChart from "./LineChart";
import MetricCard from "./MetricCard";
import ErrorCard from "./ErrorCard";
import { formatValue } from "../utils/formatters";

/**
 * Compute min/max/average/latest over a series of `{ value }` points,
 * ignoring nulls.
 *
 * @param {Array<{value: number|null}>} points
 * @returns {{min: number|null, max: number|null, average: number|null, latest: number|null}}
 */
function computeStats(points) {
  const values = points.map((p) => p.value).filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
  if (values.length === 0) {
    return { min: null, max: null, average: null, latest: null };
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const average = values.reduce((sum, v) => sum + v, 0) / values.length;
  const latest = values[values.length - 1];
  return { min, max, average, latest };
}

/**
 * Build a complete ECharts option for a single-series sensor time
 * series, with zoom, tooltip, legend, and responsive sizing.
 *
 * @param {Array<{timestamp: string, value: number|null}>} points
 * @param {string} seriesName
 * @param {string} unit
 * @returns {Object} ECharts option.
 */
function buildOption(points, seriesName, unit) {
  const xData = points.map((p) => p.timestamp);
  const yData = points.map((p) => (p.value === null || p.value === undefined ? null : p.value));

  return {
    backgroundColor: "transparent",
    color: ["#38bdf8"],
    grid: { left: 56, right: 24, top: 48, bottom: 64 },
    legend: {
      top: 0,
      textStyle: { color: "#94a3b8" },
      data: [seriesName],
    },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => (value === null || value === undefined ? "—" : `${formatValue(value)} ${unit || ""}`.trim()),
    },
    xAxis: {
      type: "category",
      data: xData,
      axisLine: { lineStyle: { color: "#334155" } },
      axisLabel: {
        color: "#94a3b8",
        formatter: (value) => {
          const date = new Date(value);
          if (Number.isNaN(date.getTime())) return value;
          return date.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
        },
      },
    },
    yAxis: {
      type: "value",
      name: unit || undefined,
      nameTextStyle: { color: "#94a3b8" },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.12)" } },
      axisLabel: { color: "#94a3b8" },
    },
    dataZoom: [
      { type: "inside", start: 0, end: 100 },
      { type: "slider", start: 0, end: 100, height: 20, bottom: 8 },
    ],
    series: [
      {
        name: seriesName,
        type: "line",
        data: yData,
        showSymbol: points.length <= 60,
        symbolSize: 5,
        smooth: false,
        connectNulls: false,
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.08 },
      },
    ],
  };
}

/**
 * A historical sensor trend chart with Min/Max/Average/Latest stat
 * cards, built for the Trends page.
 *
 * @param {Object} props
 * @param {Array<{timestamp: string, value: number|null}>} props.points - Historical points, oldest first.
 * @param {string} props.sensorLabel - Human friendly sensor name, used as the series name.
 * @param {string} [props.unit] - Unit of measurement.
 */
export default function TrendChart({ points, sensorLabel, unit }) {
  const stats = useMemo(() => computeStats(points || []), [points]);
  const option = useMemo(
    () => buildOption(points || [], sensorLabel, unit),
    [points, sensorLabel, unit]
  );

  if (!points || points.length === 0) {
    return <ErrorCard variant="no-data" detail="No readings were found for the selected time range." />;
  }

  return (
    <Stack spacing={2}>
      <Grid container spacing={1.5}>
        <Grid item xs={6} sm={3}>
          <MetricCard label="Minimum" value={formatValue(stats.min)} unit={unit} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <MetricCard label="Maximum" value={formatValue(stats.max)} unit={unit} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <MetricCard label="Average" value={formatValue(stats.average)} unit={unit} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <MetricCard label="Latest" value={formatValue(stats.latest)} unit={unit} emphasis="primary.main" />
        </Grid>
      </Grid>
      <Box>
        <LineChart option={option} height={380} ariaLabel={`${sensorLabel} trend chart`} />
        <Typography variant="caption" color="text.secondary">
          {points.length} reading{points.length === 1 ? "" : "s"} shown. Scroll/drag the slider below the
          chart, or scroll on the chart itself, to zoom.
        </Typography>
      </Box>
    </Stack>
  );
}
