import OpacityIcon from "@mui/icons-material/Opacity";
import ScienceIcon from "@mui/icons-material/Science";
import BoltIcon from "@mui/icons-material/Bolt";
import ElectricBoltIcon from "@mui/icons-material/ElectricBolt";
import BlurOnIcon from "@mui/icons-material/BlurOn";
import ThermostatIcon from "@mui/icons-material/Thermostat";
import AirIcon from "@mui/icons-material/Air";
import CompressIcon from "@mui/icons-material/Compress";
import WavesIcon from "@mui/icons-material/Waves";
import HeightIcon from "@mui/icons-material/Height";
import UmbrellaIcon from "@mui/icons-material/Umbrella";
import AirlineSeatFlatIcon from "@mui/icons-material/Speed";
import WbSunnyIcon from "@mui/icons-material/WbSunny";
import PlaceIcon from "@mui/icons-material/Place";
import SensorsIcon from "@mui/icons-material/Sensors";

/**
 * Cosmetic-only per-sensor presentation hints (icon + a reasonable
 * gauge min/max for the dial). This never determines what data is
 * requested or how it's validated - that's entirely the backend's
 * responsibility (`app/config/sensors.yaml`). If a sensor isn't
 * listed here, {@link getSensorMeta} falls back to a sensible
 * generic default so the dashboard still renders correctly for any
 * sensor the backend reports.
 */
const SENSOR_META = {
  dissolved_oxygen: { icon: OpacityIcon, min: 0, max: 20, color: "#38bdf8" },
  ph_level: { icon: ScienceIcon, min: 0, max: 14, color: "#a78bfa" },
  conductivity: { icon: BoltIcon, min: 0, max: 20000, color: "#facc15" },
  orp: { icon: ElectricBoltIcon, min: -1000, max: 1000, color: "#fb923c" },
  turbidity: { icon: BlurOnIcon, min: 0, max: 4000, color: "#a3a3a3" },
  water_temperature: { icon: ThermostatIcon, min: -5, max: 45, color: "#38bdf8" },
  air_temperature: { icon: ThermostatIcon, min: -20, max: 60, color: "#f97316" },
  humidity: { icon: AirIcon, min: 0, max: 100, color: "#34d399" },
  barometric_pressure: { icon: CompressIcon, min: 800, max: 1100, color: "#60a5fa" },
  water_level: { icon: WavesIcon, min: 0, max: 10, color: "#22d3ee" },
  river_depth: { icon: HeightIcon, min: 0, max: 15, color: "#0ea5e9" },
  rainfall: { icon: UmbrellaIcon, min: 0, max: 500, color: "#818cf8" },
  wind_speed: { icon: AirlineSeatFlatIcon, min: 0, max: 60, color: "#5eead4" },
  par: { icon: WbSunnyIcon, min: 0, max: 3000, color: "#fbbf24" },
  gps_location: { icon: PlaceIcon, min: -180, max: 180, color: "#f472b6" },
};

const DEFAULT_META = { icon: SensorsIcon, min: 0, max: 100, color: "#38bdf8" };

/**
 * Look up display metadata for a sensor key.
 *
 * @param {string} sensorName
 * @returns {{icon: React.ComponentType, min: number, max: number, color: string}}
 */
export function getSensorMeta(sensorName) {
  return SENSOR_META[sensorName] || DEFAULT_META;
}

/**
 * Color used to represent each quality/validation/calculation status
 * consistently across gauges, tables, and analytics cards.
 *
 * @param {string} status
 * @returns {"success"|"warning"|"error"|"default"} An MUI color name.
 */
export function getStatusColor(status) {
  switch (status) {
    case "good":
    case "valid":
    case "OK":
    case "ok":
      return "success";
    case "out_of_range":
      return "warning";
    case "invalid":
    case "ERROR":
    case "error":
    case "degraded":
      return "error";
    case "NOT_COMPUTABLE":
      return "warning";
    case "no_data":
    default:
      return "default";
  }
}
