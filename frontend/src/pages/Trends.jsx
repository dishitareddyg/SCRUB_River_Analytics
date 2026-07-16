import { useCallback, useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Grid from "@mui/material/Grid";

import TrendChart from "../components/TrendChart";
import StatisticsPanel from "../components/StatisticsPanel";
import ComparisonPanel from "../components/ComparisonPanel";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorCard, { variantFromApiError } from "../components/ErrorCard";
import { usePolling } from "../hooks/usePolling";
import {
  getSystemInfo,
  getSensorHistory,
  getHistoricalStatistics,
  getHistoricalTrends,
  getHistoricalComparison,
} from "../services/sensorService";

// Mirrors app/historical/utils.py::HistoryWindow - "hour"/"day"/"week"/
// "month" also match the legacy /history/sensor `interval` shortcut,
// so the same selection drives both the chart and the new
// statistics/trend/comparison endpoints without translation.
const TIME_RANGES = [
  { value: "hour", label: "Last Hour" },
  { value: "day", label: "24 Hours" },
  { value: "week", label: "7 Days" },
  { value: "month", label: "30 Days" },
  { value: "quarter", label: "90 Days" },
  { value: "year", label: "1 Year" },
];

// The legacy `GET /history/sensor` chart endpoint only understands
// this narrower set of interval shortcuts (see
// app/api/schemas/history.py::HistoryInterval) - "quarter"/"year"
// selections still drive the chart via an explicit start/end range,
// computed below, rather than an unsupported `interval` value.
const CHART_INTERVALS = new Set(["hour", "day", "week", "month"]);
const RANGE_DAYS = { quarter: 90, year: 365 };

const NONE_COMPARISON = "__none__";

export default function Trends() {
  const [sensors, setSensors] = useState([]);
  const [sensorsLoading, setSensorsLoading] = useState(true);
  const [sensorsError, setSensorsError] = useState(null);

  const [selectedSensor, setSelectedSensor] = useState("");
  const [selectedRange, setSelectedRange] = useState("day");
  const [comparisonSensor, setComparisonSensor] = useState(NONE_COMPARISON);

  useEffect(() => {
    let cancelled = false;
    setSensorsLoading(true);
    getSystemInfo()
      .then((info) => {
        if (cancelled) return;
        const configured = info.configured_sensors || [];
        setSensors(configured);
        if (configured.length > 0) {
          const preferred = configured.find((s) => s.enabled) || configured[0];
          setSelectedSensor(preferred.sensor_name);
        }
      })
      .catch((err) => {
        if (!cancelled) setSensorsError(err);
      })
      .finally(() => {
        if (!cancelled) setSensorsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchHistory = useCallback(() => {
    if (!selectedSensor) return Promise.resolve(null);
    if (CHART_INTERVALS.has(selectedRange)) {
      return getSensorHistory(selectedSensor, { interval: selectedRange, pageSize: 2000 });
    }
    const end = new Date();
    const start = new Date(end.getTime() - RANGE_DAYS[selectedRange] * 24 * 60 * 60 * 1000);
    return getSensorHistory(selectedSensor, {
      start: start.toISOString(),
      end: end.toISOString(),
      pageSize: 2000,
    });
  }, [selectedSensor, selectedRange]);

  const { data, error, loading, refresh } = usePolling(fetchHistory, null, [
    selectedSensor,
    selectedRange,
  ]);

  const fetchStatistics = useCallback(() => {
    if (!selectedSensor) return Promise.resolve(null);
    return getHistoricalStatistics(selectedSensor, { window: selectedRange });
  }, [selectedSensor, selectedRange]);
  const { data: statistics } = usePolling(fetchStatistics, null, [selectedSensor, selectedRange]);

  const fetchTrend = useCallback(() => {
    if (!selectedSensor) return Promise.resolve(null);
    return getHistoricalTrends(selectedSensor, { window: selectedRange });
  }, [selectedSensor, selectedRange]);
  const { data: trend } = usePolling(fetchTrend, null, [selectedSensor, selectedRange]);

  const fetchComparison = useCallback(() => {
    if (!selectedSensor || comparisonSensor === NONE_COMPARISON) return Promise.resolve(null);
    return getHistoricalComparison(selectedSensor, comparisonSensor, { window: selectedRange });
  }, [selectedSensor, comparisonSensor, selectedRange]);
  const { data: comparison, error: comparisonError } = usePolling(fetchComparison, null, [
    selectedSensor,
    comparisonSensor,
    selectedRange,
  ]);

  const selectedSensorMeta = useMemo(
    () => sensors.find((s) => s.sensor_name === selectedSensor),
    [sensors, selectedSensor]
  );

  const comparisonOptions = useMemo(
    () => sensors.filter((s) => s.sensor_name !== selectedSensor),
    [sensors, selectedSensor]
  );

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" gutterBottom>
          Trends
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Explore historical sensor readings, statistics, and trends. Data is fetched on demand when you
          change the sensor, time range, or comparison selection.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth size="small" disabled={sensorsLoading || sensors.length === 0}>
              <InputLabel id="trends-sensor-label">Sensor</InputLabel>
              <Select
                labelId="trends-sensor-label"
                label="Sensor"
                value={selectedSensor}
                onChange={(event) => setSelectedSensor(event.target.value)}
              >
                {sensors.map((sensor) => (
                  <MenuItem key={sensor.sensor_name} value={sensor.sensor_name}>
                    {sensor.display_name}
                    {!sensor.enabled ? " (disabled)" : ""}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth size="small" disabled={sensorsLoading || comparisonOptions.length === 0}>
              <InputLabel id="trends-comparison-label">Compare With</InputLabel>
              <Select
                labelId="trends-comparison-label"
                label="Compare With"
                value={comparisonSensor}
                onChange={(event) => setComparisonSensor(event.target.value)}
              >
                <MenuItem value={NONE_COMPARISON}>None</MenuItem>
                {comparisonOptions.map((sensor) => (
                  <MenuItem key={sensor.sensor_name} value={sensor.sensor_name}>
                    {sensor.display_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md="auto">
            <ToggleButtonGroup
              value={selectedRange}
              exclusive
              size="small"
              onChange={(_event, value) => value && setSelectedRange(value)}
              aria-label="Time range"
            >
              {TIME_RANGES.map((range) => (
                <ToggleButton key={range.value} value={range.value}>
                  {range.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Grid>
        </Grid>
      </Paper>

      {sensorsLoading ? (
        <LoadingSpinner message="Loading sensor list..." />
      ) : sensorsError ? (
        <ErrorCard variant={variantFromApiError(sensorsError)} detail={sensorsError.message} />
      ) : sensors.length === 0 ? (
        <ErrorCard variant="no-data" detail="The backend has no configured sensors." />
      ) : (
        <>
          <StatisticsPanel
            statistics={statistics}
            trend={trend}
            unit={statistics?.unit || selectedSensorMeta?.unit}
          />

          {comparisonSensor !== NONE_COMPARISON ? (
            comparisonError ? (
              <ErrorCard variant={variantFromApiError(comparisonError)} detail={comparisonError.message} />
            ) : (
              <ComparisonPanel comparison={comparison} />
            )
          ) : null}

          {loading ? (
            <LoadingSpinner message="Loading history..." />
          ) : error ? (
            <ErrorCard variant={variantFromApiError(error)} detail={error.message} onRetry={refresh} />
          ) : (
            <TrendChart
              points={data?.points || []}
              sensorLabel={selectedSensorMeta?.display_name || selectedSensor}
              unit={data?.unit || selectedSensorMeta?.unit}
            />
          )}
        </>
      )}
    </Stack>
  );
}
