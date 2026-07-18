import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import LinearProgress from "@mui/material/LinearProgress";
import Chip from "@mui/material/Chip";

const SOURCE_LABELS = {
  domestic_sewage: "Domestic Sewage",
  agricultural_runoff: "Agricultural Runoff",
  industrial_effluent: "Industrial Effluent",
  stormwater: "Stormwater",
  natural_variation: "Natural Variation",
  unknown: "Unknown",
};

/**
 * Backs the Prediction page's Pollution Source Probabilities panel,
 * from `GET /ml/pollution` (see
 * `app/ml/schemas.py::PollutionProbabilityData`). Rule-assisted, not
 * a confident determination - presented as a distribution, never a
 * single verdict.
 *
 * @param {Object} props
 * @param {Object|null} props.pollution - A `PollutionProbabilityData`
 *   payload, or `null` while loading.
 */
export default function PollutionSourceProbabilities({ pollution }) {
  const isInsufficientData = pollution?.status === "insufficient_data";
  const probabilities = pollution?.probabilities || {};
  const entries = Object.entries(probabilities).sort(([, a], [, b]) => b - a);

  return (
    <Paper variant="outlined" sx={{ p: 2.5 }} data-testid="pollution-probabilities">
      <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
        Pollution Source Probability
      </Typography>

      {isInsufficientData ? (
        <Typography variant="body2" color="text.secondary">
          Not enough sensor data yet to estimate a pollution source.
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {entries.map(([source, probability]) => {
            const isTop = source === pollution.most_likely_source;
            return (
              <Stack key={source} spacing={0.5}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography variant="body2" fontWeight={isTop ? 600 : 400}>
                    {SOURCE_LABELS[source] || source}
                  </Typography>
                  <Typography variant="body2" color={isTop ? "primary.main" : "text.secondary"}>
                    {Math.round(probability * 100)}%
                  </Typography>
                </Stack>
                <LinearProgress
                  variant="determinate"
                  value={probability * 100}
                  color={isTop ? "primary" : "inherit"}
                  sx={{ height: 6, borderRadius: 3 }}
                />
              </Stack>
            );
          })}
          <Typography variant="caption" color="text.secondary">
            Heuristic screening signal, not a confirmed determination.
          </Typography>
          {pollution?.notes?.length > 0 && (
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
              {pollution.notes.map((note) => (
                <Chip key={note} size="small" variant="outlined" label={note} />
              ))}
            </Stack>
          )}
        </Stack>
      )}
    </Paper>
  );
}
