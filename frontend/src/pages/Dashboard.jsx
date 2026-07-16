import { useCallback, useMemo } from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import AppsIcon from "@mui/icons-material/Apps";
import StorageIcon from "@mui/icons-material/Storage";
import UsbIcon from "@mui/icons-material/Usb";
import DevicesIcon from "@mui/icons-material/Devices";
import AccessTimeIcon from "@mui/icons-material/AccessTime";

import GaugeCard from "../components/GaugeCard";
import StatusCard from "../components/StatusCard";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorCard, { variantFromApiError } from "../components/ErrorCard";
import { useAppContext } from "../context/AppContext";
import { usePolling } from "../hooks/usePolling";
import { getSystemHealth, getSystemInfo, getLiveLatest } from "../services/sensorService";
import { formatTimestamp } from "../utils/formatters";

/**
 * Fetch everything the Live Dashboard needs in one poll cycle:
 * system health, system info, and the latest sensor readings.
 *
 * @returns {Promise<{health: Object, info: Object, live: Object}>}
 */
async function fetchDashboardData() {
  const [health, info, live] = await Promise.all([
    getSystemHealth(),
    getSystemInfo(),
    getLiveLatest(),
  ]);
  return { health, info, live };
}

/**
 * Compute the most recent reading timestamp across all sensors, used
 * as the dashboard's "Last Update Time".
 *
 * @param {Array<{timestamp: string|null}>} readings
 * @returns {string|null}
 */
function latestReadingTimestamp(readings) {
  const timestamps = (readings || [])
    .map((r) => r.timestamp)
    .filter(Boolean)
    .map((t) => new Date(t).getTime())
    .filter((t) => !Number.isNaN(t));
  if (timestamps.length === 0) return null;
  return new Date(Math.max(...timestamps)).toISOString();
}

export default function Dashboard() {
  const { refreshIntervalMs } = useAppContext();

  const fetchFn = useCallback(() => fetchDashboardData(), []);
  const { data, error, loading, refresh } = usePolling(fetchFn, refreshIntervalMs);

  const readings = useMemo(() => data?.live?.readings || [], [data]);
  const lastUpdate = useMemo(() => latestReadingTimestamp(readings), [readings]);

  if (loading && !data) {
    return <LoadingSpinner message="Connecting to backend..." minHeight={320} />;
  }

  if (error && !data) {
    return <ErrorCard variant={variantFromApiError(error)} detail={error.message} onRetry={refresh} />;
  }

  const health = data?.health;
  const info = data?.info;

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" gutterBottom>
          Live Dashboard
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Real-time river monitoring - refreshed automatically every {Math.round(refreshIntervalMs / 1000)}s.
        </Typography>
      </Box>

      {error ? (
        <ErrorCard variant={variantFromApiError(error)} detail={error.message} onRetry={refresh} />
      ) : null}

      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} md={2.4}>
          <StatusCard icon={AppsIcon} label="Application Status" status={health?.application_status} />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <StatusCard icon={StorageIcon} label="Database Status" status={health?.database_status} />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <StatusCard icon={UsbIcon} label="Serial Connection" status={health?.serial_connection_status} />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <StatusCard
            icon={DevicesIcon}
            label="Connected Device"
            value={info?.connected_device || "None"}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <StatusCard icon={AccessTimeIcon} label="Last Update" value={formatTimestamp(lastUpdate)} />
        </Grid>
      </Grid>

      <Box>
        <Typography variant="h6" gutterBottom>
          Sensors
        </Typography>
        {readings.length === 0 ? (
          <ErrorCard variant="no-data" detail="No sensors are currently enabled in the backend configuration." />
        ) : (
          <Grid container spacing={2}>
            {readings.map((reading) => (
              <Grid item xs={12} sm={6} md={4} lg={3} key={reading.sensor_name}>
                <GaugeCard reading={reading} />
              </Grid>
            ))}
          </Grid>
        )}
      </Box>
    </Stack>
  );
}
