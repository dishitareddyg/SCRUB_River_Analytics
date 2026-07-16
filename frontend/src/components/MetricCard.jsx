import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

/**
 * A small card showing one labeled numeric metric, e.g. "Minimum: 6.42 mg/L".
 *
 * @param {Object} props
 * @param {string} props.label - Metric label (e.g. "Minimum").
 * @param {string} props.value - Pre-formatted display value (e.g. "6.42").
 * @param {string} [props.unit] - Unit suffix (e.g. "mg/L").
 * @param {"primary"|"text.primary"} [props.emphasis="text.primary"] - Value color.
 */
export default function MetricCard({ label, value, unit, emphasis = "text.primary" }) {
  return (
    <Card variant="outlined" sx={{ height: "100%" }} data-testid={`metric-card-${label}`}>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Stack spacing={0.5}>
          <Typography variant="caption" color="text.secondary">
            {label}
          </Typography>
          <Stack direction="row" spacing={0.5} alignItems="baseline">
            <Typography variant="h6" sx={{ color: emphasis }}>
              {value}
            </Typography>
            {unit ? (
              <Typography variant="caption" color="text.secondary">
                {unit}
              </Typography>
            ) : null}
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
