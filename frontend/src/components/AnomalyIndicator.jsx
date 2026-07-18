import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";

/**
 * Backs the Prediction page's Anomaly Indicator, from
 * `GET /ml/anomalies` (see `app/ml/schemas.py::AnomalyData`).
 *
 * @param {Object} props
 * @param {Object|null} props.anomaly - An `AnomalyData` payload, or
 *   `null` while loading.
 */
export default function AnomalyIndicator({ anomaly }) {
  const isInsufficientData = anomaly?.status === "insufficient_data";
  const isAnomaly = anomaly?.is_anomaly;
  const scorePercent = Math.round((anomaly?.anomaly_score || 0) * 100);

  return (
    <Paper variant="outlined" sx={{ p: 2.5 }} data-testid="anomaly-indicator">
      <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
        <Typography variant="subtitle1">Anomaly Detection</Typography>
        {!isInsufficientData && (
          <Chip
            size="small"
            icon={isAnomaly ? <WarningAmberIcon fontSize="small" /> : <CheckCircleOutlineIcon fontSize="small" />}
            label={isAnomaly ? "Anomaly Detected" : "Normal"}
            color={isAnomaly ? "error" : "success"}
          />
        )}
      </Stack>

      {isInsufficientData ? (
        <Typography variant="body2" color="text.secondary">
          Not enough historical data yet to run anomaly detection.
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={1} alignItems="center">
            <LinearProgress
              variant="determinate"
              value={scorePercent}
              color={isAnomaly ? "error" : "primary"}
              sx={{ flex: 1, height: 8, borderRadius: 4 }}
            />
            <Typography variant="body2" fontWeight={600} sx={{ minWidth: 44, textAlign: "right" }}>
              {scorePercent}%
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary">
            Confidence: {Math.round((anomaly?.confidence || 0) * 100)}%
          </Typography>
          {anomaly?.contributing_parameters?.length > 0 && (
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
              <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
                Contributing:
              </Typography>
              {anomaly.contributing_parameters.map((param) => (
                <Chip key={param} size="small" variant="outlined" label={param.replace(/_/g, " ")} />
              ))}
            </Stack>
          )}
        </Stack>
      )}
    </Paper>
  );
}
