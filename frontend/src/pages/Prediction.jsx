import { useCallback, useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import Grid from "@mui/material/Grid";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";

import ForecastCard from "../components/ForecastCard";
import AnomalyIndicator from "../components/AnomalyIndicator";
import PollutionSourceProbabilities from "../components/PollutionSourceProbabilities";
import RiverHealthForecastCard from "../components/RiverHealthForecastCard";
import TrendChart from "../components/TrendChart";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorCard, { variantFromApiError } from "../components/ErrorCard";
import { usePolling } from "../hooks/usePolling";
import {
  getSystemInfo,
  getSensorHistory,
  getAnalyticsHistory,
  getMlPredictions,
  getMlAnomalies,
  getMlPollution,
  getMlRiverHealth,
} from "../services/sensorService";

// Mirrors app.ml.utils.DEFAULT_TREND_PARAMETERS - the parameters
// GET /ml/predictions supports out of the box. Every entry except
// river_discharge is a raw sensor key (GET /history/sensor/{name});
// river_discharge is a derived analytics parameter
// (GET /history/analytics/{param}) - ANALYTICS_TREND_PARAMETERS below
// tracks which is which so the Trend Chart fetches from the right
// endpoint.
const TREND_PARAMETERS = [
  "dissolved_oxygen",
  "ph_level",
  "conductivity",
  "water_temperature",
  "water_level",
  "river_discharge",
];
const ANALYTICS_TREND_PARAMETERS = new Set(["river_discharge"]);

// Mirrors app.ml.utils.PredictionHorizon.
const HORIZONS = [
  { value: "next_hour", label: "Next Hour" },
  { value: "next_day", label: "Next Day" },
  { value: "next_week", label: "Next Week" },
];

/**
 * One forecast card wired to `GET /ml/predictions` for a single
 * parameter - split out from {@link Prediction} so each parameter's
 * `usePolling` call is a separate component instance (parameters are
 * a fixed, known-at-compile-time list, so this does not violate the
 * rules of hooks).
 *
 * @param {Object} props
 * @param {string} props.parameter
 * @param {string} props.horizon
 * @param {string} [props.deviceName]
 */
function ForecastCardContainer({ parameter, horizon, deviceName }) {
  const fetchPrediction = useCallback(
    () => getMlPredictions(parameter, { horizon, deviceName }),
    [parameter, horizon, deviceName]
  );
  const { data } = usePolling(fetchPrediction, null, [parameter, horizon, deviceName]);
  return <ForecastCard prediction={data} parameter={parameter} />;
}

export default function Prediction() {
  const [connectedDevice, setConnectedDevice] = useState(null);
  const [infoLoading, setInfoLoading] = useState(true);
  const [infoError, setInfoError] = useState(null);
  const [horizon, setHorizon] = useState("next_day");
  const [chartParameter, setChartParameter] = useState(TREND_PARAMETERS[0]);

  useEffect(() => {
    let cancelled = false;
    setInfoLoading(true);
    getSystemInfo()
      .then((info) => {
        if (cancelled) return;
        setConnectedDevice(info.connected_device || null);
      })
      .catch((err) => {
        if (!cancelled) setInfoError(err);
      })
      .finally(() => {
        if (!cancelled) setInfoLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchAnomaly = useCallback(() => getMlAnomalies({ deviceName: connectedDevice || undefined }), [
    connectedDevice,
  ]);
  const { data: anomaly, error: anomalyError } = usePolling(fetchAnomaly, null, [connectedDevice]);

  const fetchPollution = useCallback(() => getMlPollution({ deviceName: connectedDevice || undefined }), [
    connectedDevice,
  ]);
  const { data: pollution, error: pollutionError } = usePolling(fetchPollution, null, [connectedDevice]);

  const fetchRiverHealth = useCallback(
    () => getMlRiverHealth({ horizon, deviceName: connectedDevice || undefined }),
    [horizon, connectedDevice]
  );
  const { data: riverHealth, error: riverHealthError } = usePolling(fetchRiverHealth, null, [
    horizon,
    connectedDevice,
  ]);

  const fetchChartHistory = useCallback(() => {
    const options = { interval: "week", pageSize: 1000, deviceName: connectedDevice || undefined };
    return ANALYTICS_TREND_PARAMETERS.has(chartParameter)
      ? getAnalyticsHistory(chartParameter, options)
      : getSensorHistory(chartParameter, options);
  }, [chartParameter, connectedDevice]);
  const { data: chartHistory, loading: chartLoading, error: chartError } = usePolling(fetchChartHistory, null, [
    chartParameter,
    connectedDevice,
  ]);

  const chartParameterLabel = useMemo(
    () => chartParameter.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    [chartParameter]
  );

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" gutterBottom>
          AI Predictions
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Lightweight, on-demand forecasts, anomaly detection, pollution source probabilities, and a river
          health forecast from the AI Decision Support Engine. Confidence scores reflect model fit, not
          certainty.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Grid container spacing={2} alignItems="center" justifyContent="space-between">
          <Grid item>
            <Typography variant="caption" color="text.secondary">
              Device: {connectedDevice || "All devices"}
            </Typography>
          </Grid>
          <Grid item>
            <ToggleButtonGroup
              value={horizon}
              exclusive
              size="small"
              onChange={(_event, value) => value && setHorizon(value)}
              aria-label="Forecast horizon"
            >
              {HORIZONS.map((h) => (
                <ToggleButton key={h.value} value={h.value}>
                  {h.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Grid>
        </Grid>
      </Paper>

      {infoLoading ? (
        <LoadingSpinner message="Loading system info..." />
      ) : infoError ? (
        <ErrorCard variant={variantFromApiError(infoError)} detail={infoError.message} />
      ) : (
        <>
          <Box>
            <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
              Trend Predictions
            </Typography>
            <Grid container spacing={2}>
              {TREND_PARAMETERS.map((parameter) => (
                <Grid item xs={12} sm={6} md={4} key={parameter}>
                  <ForecastCardContainer parameter={parameter} horizon={horizon} deviceName={connectedDevice} />
                </Grid>
              ))}
            </Grid>
          </Box>

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              {anomalyError ? (
                <ErrorCard variant={variantFromApiError(anomalyError)} detail={anomalyError.message} />
              ) : (
                <AnomalyIndicator anomaly={anomaly} />
              )}
            </Grid>
            <Grid item xs={12} md={6}>
              {riverHealthError ? (
                <ErrorCard variant={variantFromApiError(riverHealthError)} detail={riverHealthError.message} />
              ) : (
                <RiverHealthForecastCard forecast={riverHealth} />
              )}
            </Grid>
          </Grid>

          {pollutionError ? (
            <ErrorCard variant={variantFromApiError(pollutionError)} detail={pollutionError.message} />
          ) : (
            <PollutionSourceProbabilities pollution={pollution} />
          )}

          <Box>
            <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1.5 }}>
              <Typography variant="subtitle1">Trend Chart</Typography>
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel id="prediction-chart-parameter-label">Parameter</InputLabel>
                <Select
                  labelId="prediction-chart-parameter-label"
                  label="Parameter"
                  value={chartParameter}
                  onChange={(event) => setChartParameter(event.target.value)}
                >
                  {TREND_PARAMETERS.map((parameter) => (
                    <MenuItem key={parameter} value={parameter}>
                      {parameter.replace(/_/g, " ")}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
            {chartLoading ? (
              <LoadingSpinner message="Loading chart..." />
            ) : chartError ? (
              <ErrorCard variant={variantFromApiError(chartError)} detail={chartError.message} />
            ) : (
              <TrendChart
                points={chartHistory?.points || []}
                sensorLabel={chartParameterLabel}
                unit={chartHistory?.unit}
              />
            )}
          </Box>
        </>
      )}
    </Stack>
  );
}
