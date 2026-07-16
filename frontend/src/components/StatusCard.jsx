import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Box from "@mui/material/Box";
import { getStatusColor } from "../utils/sensorMeta";

/**
 * A compact card pairing a label with either a colored status chip
 * or a plain value - used for the Live Dashboard's system status
 * strip (Application Status, Database Status, Serial Connection
 * Status, Connected Device, Last Update Time).
 *
 * @param {Object} props
 * @param {React.ComponentType} [props.icon] - An MUI icon component.
 * @param {string} props.label - The status row's label (e.g. "Database Status").
 * @param {string} [props.status] - A status keyword (e.g. "ok", "degraded",
 *   "disconnected"); rendered as a colored Chip. Mutually exclusive
 *   with `value`.
 * @param {string} [props.value] - A plain text value (e.g. a device
 *   name or timestamp) to show instead of a status chip.
 * @param {string} [props.helperText] - Optional secondary line.
 */
export default function StatusCard({ icon: Icon, label, status, value, helperText }) {
  return (
    <Card variant="outlined" sx={{ height: "100%" }}>
      <CardContent sx={{ py: 1.75, "&:last-child": { pb: 1.75 } }}>
        <Stack direction="row" spacing={1.5} alignItems="center">
          {Icon ? (
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 36,
                height: 36,
                borderRadius: 2,
                bgcolor: "rgba(56, 189, 248, 0.1)",
                color: "primary.main",
                flexShrink: 0,
              }}
            >
              <Icon fontSize="small" />
            </Box>
          ) : null}
          <Stack spacing={0.25} sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="caption" color="text.secondary" noWrap>
              {label}
            </Typography>
            {status !== undefined ? (
              <Chip
                size="small"
                label={status || "unknown"}
                color={getStatusColor(status)}
                sx={{ alignSelf: "flex-start", textTransform: "capitalize" }}
              />
            ) : (
              <Typography variant="body2" fontWeight={600} noWrap title={value}>
                {value ?? "—"}
              </Typography>
            )}
            {helperText ? (
              <Typography variant="caption" color="text.secondary" noWrap>
                {helperText}
              </Typography>
            ) : null}
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
