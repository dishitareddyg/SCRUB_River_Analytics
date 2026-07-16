import { useMemo } from "react";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Box from "@mui/material/Box";
import LineChart from "./LineChart";
import { getSensorMeta, getStatusColor } from "../utils/sensorMeta";
import { formatValue, formatTimestamp } from "../utils/formatters";

/**
 * Build the ECharts gauge option for one sensor reading.
 *
 * @param {number|null} value
 * @param {number} min
 * @param {number} max
 * @param {string} unit
 * @param {string} color
 * @returns {Object} ECharts option.
 */
function buildGaugeOption(value, min, max, unit, color) {
  const hasValue = value !== null && value !== undefined && !Number.isNaN(value);
  const clamped = hasValue ? Math.min(Math.max(value, min), max) : min;

  return {
    backgroundColor: "transparent",
    series: [
      {
        type: "gauge",
        min,
        max,
        radius: "92%",
        center: ["50%", "62%"],
        startAngle: 210,
        endAngle: -30,
        progress: {
          show: true,
          width: 12,
          itemStyle: { color: hasValue ? color : "#334155" },
        },
        axisLine: {
          lineStyle: {
            width: 12,
            color: [[1, "rgba(148, 163, 184, 0.18)"]],
          },
        },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        anchor: { show: false },
        title: { show: false },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, "-6%"],
          fontSize: 26,
          fontWeight: 600,
          color: hasValue ? "#e2e8f0" : "#64748b",
          formatter: () => (hasValue ? formatValue(value) : "No data"),
        },
        data: [{ value: clamped }],
      },
    ],
  };
}

/**
 * A gauge card for one live sensor reading: dial, value, unit,
 * timestamp, and a quality-status chip.
 *
 * @param {Object} props
 * @param {Object} props.reading - A LiveSensorReading payload
 *   (`{ sensor_name, display_name, value, unit, timestamp,
 *   quality_status, validation_status }`).
 */
export default function GaugeCard({ reading }) {
  const meta = getSensorMeta(reading.sensor_name);
  const Icon = meta.icon;

  const option = useMemo(
    () => buildGaugeOption(reading.value, meta.min, meta.max, reading.unit, meta.color),
    [reading.value, meta.min, meta.max, reading.unit, meta.color]
  );

  return (
    <Card variant="outlined" sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <CardContent sx={{ flex: 1, display: "flex", flexDirection: "column", pb: "16px !important" }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
            <Icon fontSize="small" sx={{ color: meta.color, flexShrink: 0 }} />
            <Typography variant="subtitle2" noWrap title={reading.display_name}>
              {reading.display_name}
            </Typography>
          </Stack>
          <Chip
            size="small"
            label={(reading.quality_status || "unknown").replace(/_/g, " ")}
            color={getStatusColor(reading.quality_status)}
            sx={{ textTransform: "capitalize", flexShrink: 0 }}
          />
        </Stack>

        <Box sx={{ flex: 1, minHeight: 150 }}>
          <LineChart option={option} height={150} ariaLabel={`${reading.display_name} gauge`} />
        </Box>

        <Stack direction="row" justifyContent="space-between" alignItems="baseline">
          <Typography variant="caption" color="text.secondary">
            {reading.unit || ""}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {formatTimestamp(reading.timestamp)}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  );
}
