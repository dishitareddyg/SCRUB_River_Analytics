import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Paper from "@mui/material/Paper";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";

/**
 * A simple, read-only table of configured sensors.
 *
 * @param {Object} props
 * @param {Array<{sensor_name: string, display_name: string, unit: string|null, enabled: boolean}>} props.sensors
 */
export default function SensorTable({ sensors }) {
  if (!sensors || sensors.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No sensors are configured.
      </Typography>
    );
  }

  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label="Configured sensors">
        <TableHead>
          <TableRow>
            <TableCell>Sensor</TableCell>
            <TableCell>Display Name</TableCell>
            <TableCell>Unit</TableCell>
            <TableCell align="right">Status</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {sensors.map((sensor) => (
            <TableRow key={sensor.sensor_name} hover>
              <TableCell sx={{ fontFamily: "monospace", fontSize: "0.8rem" }}>
                {sensor.sensor_name}
              </TableCell>
              <TableCell>{sensor.display_name}</TableCell>
              <TableCell>{sensor.unit || "—"}</TableCell>
              <TableCell align="right">
                <Chip
                  size="small"
                  label={sensor.enabled ? "Enabled" : "Disabled"}
                  color={sensor.enabled ? "success" : "default"}
                  variant={sensor.enabled ? "filled" : "outlined"}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
