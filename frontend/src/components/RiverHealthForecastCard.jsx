import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import { formatValue } from "../utils/formatters";

const CATEGORY_COLOR = {
  excellent: "success",
  good: "success",
  fair: "warning",
  poor: "error",
  critical: "error",
};

const CATEGORY_LABEL = {
  excellent: "Excellent",
  good: "Good",
  fair: "Fair",
  poor: "Poor",
  critical: "Critical",
};

/**
 * Backs the Prediction page's River Health Forecast panel, from
 * `GET /ml/river-health` (see
 * `app/ml/schemas.py::RiverHealthForecastData`).
 *
 * @param {Object} props
 * @param {Object|null} props.forecast - A `RiverHealthForecastData`
 *   payload, or `null` while loading.
 */
export default function RiverHealthForecastCard({ forecast }) {
  const isInsufficientData = forecast?.status === "insufficient_data";
  const category = forecast?.health_category;

  return (
    <Paper variant="outlined" sx={{ p: 2.5 }} data-testid="river-health-forecast">
      <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
        <Typography variant="subtitle1">River Health Forecast</Typography>
        {!isInsufficientData && category && (
          <Chip size="small" label={CATEGORY_LABEL[category] || category} color={CATEGORY_COLOR[category] || "default"} />
        )}
      </Stack>

      {isInsufficientData ? (
        <Typography variant="body2" color="text.secondary">
          Not enough historical data yet to forecast river health.
        </Typography>
      ) : (
        <Stack direction="row" spacing={4} alignItems="baseline">
          <Stack>
            <Typography variant="caption" color="text.secondary">
              Current
            </Typography>
            <Typography variant="h5" fontWeight={700}>
              {formatValue(forecast?.current_score, 0)}
            </Typography>
          </Stack>
          <Stack>
            <Typography variant="caption" color="text.secondary">
              Predicted
            </Typography>
            <Typography variant="h5" fontWeight={700} color="primary.main">
              {formatValue(forecast?.predicted_score, 0)}
            </Typography>
          </Stack>
          <Stack>
            <Typography variant="caption" color="text.secondary">
              Confidence
            </Typography>
            <Typography variant="h5" fontWeight={700}>
              {Math.round((forecast?.confidence || 0) * 100)}%
            </Typography>
          </Stack>
        </Stack>
      )}
    </Paper>
  );
}
