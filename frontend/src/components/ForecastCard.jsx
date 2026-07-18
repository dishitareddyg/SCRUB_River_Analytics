import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import { getSensorMeta } from "../utils/sensorMeta";
import { formatValue } from "../utils/formatters";

/**
 * One parameter's short-horizon forecast card, backed by
 * `GET /ml/predictions` (see `app/ml/schemas.py::TrendPredictionData`).
 *
 * @param {Object} props
 * @param {Object|null} props.prediction - A `TrendPredictionData`
 *   payload, or `null` while loading.
 * @param {string} props.parameter - The parameter key (used to look
 *   up a display icon/color as a fallback while loading).
 */
export default function ForecastCard({ prediction, parameter }) {
  const meta = getSensorMeta(parameter);
  const Icon = meta.icon;

  const status = prediction?.status;
  const isInsufficientData = status === "insufficient_data";
  const direction =
    prediction?.predicted_value !== null &&
    prediction?.predicted_value !== undefined &&
    prediction?.current_value !== null &&
    prediction?.current_value !== undefined
      ? prediction.predicted_value >= prediction.current_value
        ? "up"
        : "down"
      : null;

  return (
    <Card variant="outlined" sx={{ height: "100%" }} data-testid={`forecast-card-${parameter}`}>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
          <Icon fontSize="small" sx={{ color: meta.color }} />
          <Typography variant="subtitle2" noWrap title={prediction?.display_name || parameter}>
            {prediction?.display_name || parameter}
          </Typography>
        </Stack>

        {isInsufficientData ? (
          <Typography variant="body2" color="text.secondary">
            Not enough historical data yet.
          </Typography>
        ) : (
          <>
            <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 0.5 }}>
              <Typography variant="h5" fontWeight={700}>
                {formatValue(prediction?.predicted_value)}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {prediction?.unit || ""}
              </Typography>
              {direction === "up" ? (
                <TrendingUpIcon fontSize="small" color="success" />
              ) : direction === "down" ? (
                <TrendingDownIcon fontSize="small" color="error" />
              ) : null}
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              currently {formatValue(prediction?.current_value)} {prediction?.unit || ""} · range{" "}
              {formatValue(prediction?.confidence_interval_lower)}–
              {formatValue(prediction?.confidence_interval_upper)}
            </Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <LinearProgress
                variant="determinate"
                value={(prediction?.model_confidence || 0) * 100}
                sx={{ flex: 1, height: 6, borderRadius: 3 }}
              />
              <Chip
                size="small"
                variant="outlined"
                label={`${Math.round((prediction?.model_confidence || 0) * 100)}% confidence`}
              />
            </Stack>
          </>
        )}
      </CardContent>
    </Card>
  );
}
