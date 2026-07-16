import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Grid from "@mui/material/Grid";
import Chip from "@mui/material/Chip";
import MetricCard from "./MetricCard";
import { formatValue } from "../utils/formatters";

/**
 * Classify a Pearson correlation coefficient into a short, human
 * readable strength label.
 *
 * @param {number|null|undefined} correlation
 * @returns {{label: string, color: "success"|"warning"|"default"}}
 */
function correlationStrength(correlation) {
  if (correlation === null || correlation === undefined) {
    return { label: "Not enough overlapping data", color: "default" };
  }
  const magnitude = Math.abs(correlation);
  const direction = correlation >= 0 ? "Positive" : "Negative";
  if (magnitude >= 0.7) return { label: `Strong ${direction}`, color: "success" };
  if (magnitude >= 0.3) return { label: `Moderate ${direction}`, color: "warning" };
  return { label: "Weak / No Correlation", color: "default" };
}

/**
 * Backs the Trends page's Comparison Selector - shows two parameters'
 * summary statistics side by side plus their correlation, from
 * `GET /history/compare`.
 *
 * @param {Object} props
 * @param {Object|null} props.comparison - A `ComparisonData` payload
 *   (see `app/historical/schemas.py::ComparisonData`), or `null`.
 */
export default function ComparisonPanel({ comparison }) {
  if (!comparison) return null;
  const strength = correlationStrength(comparison.correlation);

  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between">
          <Typography variant="subtitle1">
            {comparison.display_name_a} vs {comparison.display_name_b}
          </Typography>
          <Chip
            size="small"
            label={`${strength.label}${
              comparison.correlation !== null && comparison.correlation !== undefined
                ? ` (r = ${formatValue(comparison.correlation, 2)})`
                : ""
            }`}
            color={strength.color}
          />
        </Stack>
        <Grid container spacing={1.5}>
          <Grid item xs={6} sm={3}>
            <MetricCard label={`${comparison.display_name_a} Avg`} value={formatValue(comparison.average_a)} />
          </Grid>
          <Grid item xs={6} sm={3}>
            <MetricCard label={`${comparison.display_name_b} Avg`} value={formatValue(comparison.average_b)} />
          </Grid>
          <Grid item xs={6} sm={3}>
            <MetricCard
              label={`${comparison.display_name_a} Range`}
              value={`${formatValue(comparison.minimum_a)} – ${formatValue(comparison.maximum_a)}`}
            />
          </Grid>
          <Grid item xs={6} sm={3}>
            <MetricCard
              label={`${comparison.display_name_b} Range`}
              value={`${formatValue(comparison.minimum_b)} – ${formatValue(comparison.maximum_b)}`}
            />
          </Grid>
        </Grid>
        <Typography variant="caption" color="text.secondary">
          Based on {comparison.matched_points} time-aligned sample pair(s).
        </Typography>
      </Stack>
    </Paper>
  );
}
