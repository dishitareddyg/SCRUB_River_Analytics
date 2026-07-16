import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CloudOffIcon from "@mui/icons-material/CloudOff";
import StorageIcon from "@mui/icons-material/Storage";
import UsbOffIcon from "@mui/icons-material/UsbOff";
import SensorsOffIcon from "@mui/icons-material/SensorsOff";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";

const VARIANTS = {
  "backend-offline": {
    icon: <CloudOffIcon fontSize="inherit" />,
    title: "Backend Offline",
    message: "Could not reach the backend API. Confirm it is running and the URL in Settings is correct.",
  },
  "database-offline": {
    icon: <StorageIcon fontSize="inherit" />,
    title: "Database Offline",
    message: "The backend cannot reach its database. Live values may be unavailable until it recovers.",
  },
  "serial-disconnected": {
    icon: <UsbOffIcon fontSize="inherit" />,
    title: "Serial Disconnected",
    message: "No active connection to the Arduino. Readings shown may be stale or unavailable.",
  },
  "no-data": {
    icon: <SensorsOffIcon fontSize="inherit" />,
    title: "No Sensor Data",
    message: "No readings are available yet for this selection.",
  },
  generic: {
    icon: <ErrorOutlineIcon fontSize="inherit" />,
    title: "Something Went Wrong",
    message: "An unexpected error occurred.",
  },
};

/**
 * Map a normalized {@link import('../api/api').ApiError} to the most
 * relevant {@link ErrorCard} variant.
 *
 * @param {import('../api/api').ApiError} apiError
 * @returns {keyof typeof VARIANTS}
 */
export function variantFromApiError(apiError) {
  if (!apiError) return "generic";
  if (apiError.kind === "network") return "backend-offline";
  if (apiError.status === 404) return "no-data";
  return "generic";
}

/**
 * A friendly, specific error card for the dashboard's known failure
 * modes (backend offline, database offline, serial disconnected, no
 * sensor data) plus a generic fallback.
 *
 * @param {Object} props
 * @param {keyof typeof VARIANTS} [props.variant="generic"]
 * @param {string} [props.detail] - Optional extra detail line (e.g. the raw error message).
 * @param {() => void} [props.onRetry] - If provided, shows a "Retry" button.
 */
export default function ErrorCard({ variant = "generic", detail, onRetry }) {
  const config = VARIANTS[variant] || VARIANTS.generic;

  return (
    <Alert
      severity="error"
      icon={config.icon}
      variant="outlined"
      sx={{ alignItems: "center", "& .MuiAlert-message": { width: "100%" } }}
      action={
        onRetry ? (
          <Button color="inherit" size="small" onClick={onRetry}>
            Retry
          </Button>
        ) : undefined
      }
    >
      <AlertTitle>{config.title}</AlertTitle>
      <Box>{config.message}</Box>
      {detail ? (
        <Box sx={{ mt: 0.5, opacity: 0.75, fontSize: "0.75rem" }}>{detail}</Box>
      ) : null}
    </Alert>
  );
}
