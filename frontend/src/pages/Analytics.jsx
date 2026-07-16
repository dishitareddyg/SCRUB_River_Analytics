import { useCallback } from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

import LoadingSpinner from "../components/LoadingSpinner";
import ErrorCard, { variantFromApiError } from "../components/ErrorCard";
import { useAppContext } from "../context/AppContext";
import { usePolling } from "../hooks/usePolling";
import { getAnalyticsLatest } from "../services/sensorService";
import { formatValue, formatTimestamp } from "../utils/formatters";
import { getStatusColor } from "../utils/sensorMeta";

/**
 * One derived-parameter result card: value, unit, formula name,
 * calculation status, and timestamp.
 *
 * @param {Object} props
 * @param {Object} props.result - An AnalyticsResult payload.
 */
function AnalyticsResultCard({ result }) {
  const isOk = result.status === "OK";

  return (
    <Card variant="outlined" sx={{ height: "100%" }}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
          <Typography variant="subtitle2" sx={{ pr: 1 }}>
            {result.display_name}
          </Typography>
          <Chip
            size="small"
            label={result.status.replace(/_/g, " ")}
            color={getStatusColor(result.status)}
            sx={{ textTransform: "capitalize", flexShrink: 0 }}
          />
        </Stack>

        <Stack direction="row" spacing={0.75} alignItems="baseline" sx={{ mb: 1 }}>
          <Typography variant="h4" color={isOk ? "primary.main" : "text.disabled"}>
            {isOk ? formatValue(result.value) : "—"}
          </Typography>
          {isOk && result.unit ? (
            <Typography variant="body2" color="text.secondary">
              {result.unit}
            </Typography>
          ) : null}
        </Stack>

        {!isOk && result.missing_inputs?.length > 0 ? (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            Missing: {result.missing_inputs.join(", ")}
          </Typography>
        ) : null}

        <Stack direction="row" spacing={0.5} alignItems="center">
          <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }} noWrap title={result.formula_used}>
            {result.formula_used || "—"}
          </Typography>
          {result.reference ? (
            <Tooltip title={result.reference} placement="top">
              <InfoOutlinedIcon sx={{ fontSize: 14, color: "text.secondary" }} />
            </Tooltip>
          ) : null}
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block">
          {formatTimestamp(result.timestamp)}
        </Typography>
      </CardContent>
    </Card>
  );
}

export default function Analytics() {
  const { refreshIntervalMs } = useAppContext();

  const fetchFn = useCallback(() => getAnalyticsLatest(), []);
  const { data, error, loading, refresh } = usePolling(fetchFn, refreshIntervalMs);

  if (loading && !data) {
    return <LoadingSpinner message="Computing derived parameters..." minHeight={320} />;
  }

  if (error && !data) {
    return <ErrorCard variant={variantFromApiError(error)} detail={error.message} onRetry={refresh} />;
  }

  const results = data?.results || [];

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" gutterBottom>
          Analytics
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Derived river parameters, computed live by the Analytics Engine - refreshed every{" "}
          {Math.round(refreshIntervalMs / 1000)}s.
        </Typography>
      </Box>

      {error ? (
        <ErrorCard variant={variantFromApiError(error)} detail={error.message} onRetry={refresh} />
      ) : null}

      {results.length === 0 ? (
        <ErrorCard variant="no-data" detail="The Analytics Engine has no registered parameters." />
      ) : (
        <Grid container spacing={2}>
          {results.map((result) => (
            <Grid item xs={12} sm={6} md={4} lg={3} key={result.parameter}>
              <AnalyticsResultCard result={result} />
            </Grid>
          ))}
        </Grid>
      )}
    </Stack>
  );
}
