import { useCallback } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import Grid from "@mui/material/Grid";
import Divider from "@mui/material/Divider";
import Tooltip from "@mui/material/Tooltip";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

import SensorTable from "../components/SensorTable";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorCard, { variantFromApiError } from "../components/ErrorCard";
import { useAppContext } from "../context/AppContext";
import { usePolling } from "../hooks/usePolling";
import { getSystemInfo } from "../services/sensorService";

/**
 * One read-only "label: value" row.
 *
 * @param {Object} props
 * @param {string} props.label
 * @param {React.ReactNode} props.value
 * @param {string} [props.tooltip] - Optional explanatory tooltip icon.
 */
function InfoRow({ label, value, tooltip }) {
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 1.25 }}>
      <Stack direction="row" spacing={0.5} alignItems="center">
        <Typography variant="body2" color="text.secondary">
          {label}
        </Typography>
        {tooltip ? (
          <Tooltip title={tooltip} placement="top">
            <InfoOutlinedIcon sx={{ fontSize: 14, color: "text.secondary" }} />
          </Tooltip>
        ) : null}
      </Stack>
      <Typography variant="body2" fontWeight={600} sx={{ textAlign: "right" }}>
        {value}
      </Typography>
    </Stack>
  );
}

export default function Settings() {
  const { apiBaseUrl, refreshIntervalSeconds } = useAppContext();

  // Read-only info, fetched once - no polling needed for a settings page.
  const fetchFn = useCallback(() => getSystemInfo(), []);
  const { data, error, loading, refresh } = usePolling(fetchFn, null);

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" gutterBottom>
          Settings
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Read-only configuration overview.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="subtitle1" gutterBottom>
          Connection
        </Typography>
        <Divider sx={{ mb: 0.5 }} />
        <InfoRow label="Backend URL" value={apiBaseUrl} />
        <Divider />
        <InfoRow
          label="Sampling Interval"
          value={`${refreshIntervalSeconds}s (dashboard refresh)`}
          tooltip="Configured in this dashboard (VITE_REFRESH_INTERVAL_SECONDS). The backend API does not currently expose its own per-sensor sampling interval."
        />
      </Paper>

      {loading ? (
        <LoadingSpinner message="Loading system info..." />
      ) : error ? (
        <ErrorCard variant={variantFromApiError(error)} detail={error.message} onRetry={refresh} />
      ) : (
        <>
          <Paper variant="outlined" sx={{ p: 2.5 }}>
            <Typography variant="subtitle1" gutterBottom>
              Application
            </Typography>
            <Divider sx={{ mb: 0.5 }} />
            <Grid container>
              <Grid item xs={12} sm={6}>
                <InfoRow label="Application Version" value={data?.application_version || "—"} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <InfoRow label="Environment" value={data?.environment || "—"} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <InfoRow label="Connected Device" value={data?.connected_device || "None"} />
              </Grid>
              <Grid item xs={12} sm={6}>
                <InfoRow label="Database Type" value={data?.database_type || "—"} />
              </Grid>
            </Grid>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2.5 }}>
            <Typography variant="subtitle1" gutterBottom>
              Configured Sensors
            </Typography>
            <Divider sx={{ mb: 1.5 }} />
            <SensorTable sensors={data?.configured_sensors} />
          </Paper>
        </>
      )}
    </Stack>
  );
}
