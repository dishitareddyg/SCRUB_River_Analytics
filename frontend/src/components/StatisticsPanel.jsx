import Grid from "@mui/material/Grid";
import MetricCard from "./MetricCard";
import TrendIndicator from "./TrendIndicator";
import { formatValue } from "../utils/formatters";

/**
 * The Trends page's "Statistics Panel": a row of summary cards
 * (Minimum, Maximum, Average, Latest Value, Trend Direction) backed
 * by `GET /history/statistics/{parameter}` and
 * `GET /history/trends/{parameter}`.
 *
 * @param {Object} props
 * @param {Object|null} props.statistics - A `StatisticsData` payload
 *   (see `app/historical/schemas.py::StatisticsData`), or `null`
 *   while loading.
 * @param {Object|null} props.trend - A `TrendData` payload, or `null`
 *   while loading.
 * @param {string} [props.unit] - Unit of measurement, for card suffixes.
 */
export default function StatisticsPanel({ statistics, trend, unit }) {
  return (
    <Grid container spacing={1.5}>
      <Grid item xs={6} sm={4} md={2}>
        <MetricCard label="Minimum" value={formatValue(statistics?.minimum)} unit={unit} />
      </Grid>
      <Grid item xs={6} sm={4} md={2}>
        <MetricCard label="Maximum" value={formatValue(statistics?.maximum)} unit={unit} />
      </Grid>
      <Grid item xs={6} sm={4} md={2}>
        <MetricCard label="Average" value={formatValue(statistics?.average)} unit={unit} />
      </Grid>
      <Grid item xs={6} sm={4} md={2}>
        <MetricCard label="Median" value={formatValue(statistics?.median)} unit={unit} />
      </Grid>
      <Grid item xs={6} sm={4} md={2}>
        <MetricCard
          label="Latest Value"
          value={formatValue(statistics?.last_value)}
          unit={unit}
          emphasis="primary"
        />
      </Grid>
      <Grid item xs={6} sm={4} md={2}>
        <TrendIndicator trend={trend} />
      </Grid>
    </Grid>
  );
}
