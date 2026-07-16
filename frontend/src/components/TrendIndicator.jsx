import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import TrendingFlatIcon from "@mui/icons-material/TrendingFlat";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import { formatValue } from "../utils/formatters";

/**
 * Presentation metadata for each backend `TrendDirection` value (see
 * `app/historical/trends.py::TrendDirection`).
 */
const DIRECTION_META = {
  increasing: { label: "Increasing", icon: TrendingUpIcon, color: "success" },
  rapid_increase: { label: "Rapid Increase", icon: TrendingUpIcon, color: "success" },
  decreasing: { label: "Decreasing", icon: TrendingDownIcon, color: "error" },
  rapid_decrease: { label: "Rapid Decrease", icon: TrendingDownIcon, color: "error" },
  stable: { label: "Stable", icon: TrendingFlatIcon, color: "default" },
  insufficient_data: { label: "Insufficient Data", icon: HelpOutlineIcon, color: "default" },
};

/**
 * A compact card summarizing a parameter's trend direction, percent
 * change, rate of change, and fit confidence - backed by
 * `GET /history/trends/{parameter}`.
 *
 * @param {Object} props
 * @param {Object|null} props.trend - A `TrendData` payload (see
 *   `app/historical/schemas.py::TrendData`), or `null` while loading.
 */
export default function TrendIndicator({ trend }) {
  const direction = trend?.direction || "insufficient_data";
  const meta = DIRECTION_META[direction] || DIRECTION_META.insufficient_data;
  const Icon = meta.icon;

  return (
    <Card variant="outlined" sx={{ height: "100%" }} data-testid="trend-indicator">
      <CardContent sx={{ py: 1.75, "&:last-child": { pb: 1.75 } }}>
        <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between">
          <Stack spacing={0.5}>
            <Typography variant="caption" color="text.secondary">
              Trend
            </Typography>
            <Chip
              size="small"
              icon={<Icon fontSize="small" />}
              label={meta.label}
              color={meta.color}
              sx={{ alignSelf: "flex-start" }}
            />
          </Stack>
          <Stack spacing={0.25} alignItems="flex-end">
            <Typography variant="body2" fontWeight={600}>
              {trend?.trend_percentage !== null && trend?.trend_percentage !== undefined
                ? `${formatValue(trend.trend_percentage, 1)}%`
                : "—"}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              confidence {trend?.trend_confidence !== null && trend?.trend_confidence !== undefined
                ? formatValue(trend.trend_confidence * 100, 0)
                : "—"}
              %
            </Typography>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
