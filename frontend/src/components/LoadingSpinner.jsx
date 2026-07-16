import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Typography from "@mui/material/Typography";

/**
 * A simple centered loading indicator with an optional message.
 *
 * @param {Object} props
 * @param {string} [props.message="Loading..."] - Text shown beneath the spinner.
 * @param {number|string} [props.minHeight=200] - Minimum height of the container.
 * @param {"small"|"medium"|"large"} [props.size="medium"] - Spinner size preset.
 */
export default function LoadingSpinner({ message = "Loading...", minHeight = 200, size = "medium" }) {
  const spinnerSize = { small: 24, medium: 40, large: 56 }[size] ?? 40;

  return (
    <Box
      role="status"
      aria-live="polite"
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 1.5,
        minHeight,
        width: "100%",
        color: "text.secondary",
      }}
    >
      <CircularProgress size={spinnerSize} thickness={4} />
      {message ? <Typography variant="body2">{message}</Typography> : null}
    </Box>
  );
}
