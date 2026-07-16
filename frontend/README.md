# River Intelligence Platform — Frontend

A lightweight, industrial-style React dashboard for the River Intelligence Platform. It consumes the
existing FastAPI backend's REST API exactly as-is (see `../backend/README.md`) - this app never talks to
the Arduino, a database, MQTT, or a WebSocket directly.

## Tech Stack

- **React 18** + **Vite** - app shell and dev/build tooling
- **Material UI (MUI) v5** - components and theming
- **Apache ECharts** - gauges and trend charts (hand-rolled wrapper, no extra binding library)
- **Axios** - HTTP client
- **React Router v6** - client-side routing
- **Leaflet** - listed per the project's tech stack and installed as a dependency; see
  [GPS / Leaflet note](#gps--leaflet-note) below for why it isn't wired to a live map yet
- **Vitest** + **React Testing Library** - component/page tests

## Project Structure

```
frontend/
├── index.html
├── vite.config.js
├── package.json
├── .env.example
├── src/
│   ├── main.jsx              # Entry point
│   ├── App.jsx                # Theme, providers, routes
│   ├── api/
│   │   ├── api.js            # Axios instance + normalizeApiError()
│   │   └── api.test.js
│   ├── services/
│   │   ├── sensorService.js  # One function per backend endpoint
│   │   └── sensorService.test.js
│   ├── context/
│   │   └── AppContext.jsx    # Shared app state (React Context, no Redux)
│   ├── hooks/
│   │   ├── usePolling.js     # Polling/refresh-on-demand hook
│   │   └── usePolling.test.js
│   ├── theme/
│   │   └── theme.js          # MUI industrial dark theme
│   ├── layouts/
│   │   ├── MainLayout.jsx    # Sidebar + app bar + content area
│   │   └── MainLayout.test.jsx
│   ├── components/
│   │   ├── GaugeCard.jsx         # Live sensor gauge (ECharts)
│   │   ├── LineChart.jsx         # Generic, responsive ECharts wrapper
│   │   ├── TrendChart.jsx        # Sensor-history chart + min/max/avg/latest
│   │   ├── StatusCard.jsx        # System status chip card
│   │   ├── MetricCard.jsx        # Small labeled metric card
│   │   ├── SensorTable.jsx       # Configured-sensors table
│   │   ├── LoadingSpinner.jsx    # Centered loading indicator
│   │   ├── ErrorCard.jsx         # Backend/DB/Serial/No-data error states
│   │   └── *.test.jsx            # Co-located component tests
│   ├── pages/
│   │   ├── Dashboard.jsx     # Live Dashboard (landing page)
│   │   ├── Trends.jsx        # Historical trends
│   │   ├── Analytics.jsx     # Derived analytics
│   │   ├── Settings.jsx      # Read-only settings
│   │   └── *.test.jsx        # Co-located page rendering tests
│   ├── utils/
│   │   ├── formatters.js     # Value/timestamp formatting helpers
│   │   └── sensorMeta.js     # Per-sensor icon/color/range + status-color mapping
│   └── test/
│       ├── setup.js          # Vitest setup (jest-dom, ECharts/ResizeObserver stubs)
│       └── testUtils.jsx     # renderWithProviders() test helper
```

## Running the Frontend

Requires Node.js 18+ and the backend running (see `../backend/README.md`).

```bash
cd frontend
npm install
cp .env.example .env      # adjust VITE_API_BASE_URL if needed
npm run dev                # http://localhost:5173
```

Other scripts:

```bash
npm run build              # production build -> dist/
npm run preview            # preview the production build locally
npm run test                # run the test suite once
npm run test:watch          # run the test suite in watch mode
npm run lint                 # ESLint
```

## Environment Variables

Copy `.env.example` to `.env` (or `.env.local`) and adjust. Vite only exposes variables prefixed with
`VITE_` to client code; every one is read in `src/api/api.js` and `src/context/AppContext.jsx` - nothing
else in the app reads `import.meta.env` directly.

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base URL of the FastAPI backend (no trailing slash, no `/api/v1` suffix). |
| `VITE_REFRESH_INTERVAL_SECONDS` | `5` | How often the Live Dashboard and Analytics pages poll their endpoints. |
| `VITE_API_TIMEOUT_MS` | `8000` | Axios request timeout, in milliseconds. |

## API Configuration

The app talks exclusively to the backend's versioned REST API (`API_V1_PREFIX=/api/v1` on the backend,
hardcoded to match in `src/api/api.js` since it must match the backend exactly - see
`app/config/settings.py` in the backend). Every request goes through `src/services/sensorService.js`,
which wraps exactly these six existing endpoints and nothing else:

| Endpoint | Used by | Refresh strategy |
| --- | --- | --- |
| `GET /system/health` | Dashboard | Every `VITE_REFRESH_INTERVAL_SECONDS` |
| `GET /system/info` | Dashboard, Trends (sensor list), Settings | Dashboard: every interval. Trends/Settings: once on mount |
| `GET /live/latest` | Dashboard | Every `VITE_REFRESH_INTERVAL_SECONDS` |
| `GET /analytics/latest` | Analytics | Every `VITE_REFRESH_INTERVAL_SECONDS` |
| `GET /history/sensor/{sensor}` | Trends | Only when the selected sensor or time range changes |
| `GET /history/analytics/{parameter}` | *(wired in `sensorService.js`, not yet used by a page)* | On demand |

Every response follows the backend's standard envelope (`{ success, message, data, meta }`); every service
function unwraps `data` and resolves with it directly. On failure, `normalizeApiError()` (in `src/api/api.js`)
converts any Axios error into `{ kind: "network"|"http"|"unknown", status, message }`, which
`ErrorCard`/`variantFromApiError()` uses to render the most specific friendly error state available
(Backend Offline, No Sensor Data, or a generic message) - see `src/components/ErrorCard.jsx`.

### A note on `/live/latest`

This endpoint returns one reading per **enabled** sensor only (per `sensors.yaml` on the backend). The
Live Dashboard renders exactly what it receives - if only 3 of the 15 possible sensors are enabled on a
given deployment, only 3 gauges appear. Nothing in the frontend hardcodes the list of 15 sensor types from
the project spec; it is entirely data-driven from the API response. `src/utils/sensorMeta.js` supplies a
cosmetic icon/color/gauge-range for every sensor key named in the spec (and a sensible generic fallback for
anything else the backend ever reports), but never changes what data is requested or how it's validated.

### GPS / Leaflet note

Leaflet is installed and listed as a dependency per the project's tech stack. However, `GET /live/latest`'s
`gps_location` reading is a single numeric field (see the backend's `LiveSensorReading.value: float`
schema), not a `{lat, lon}` pair, so there isn't yet a coordinate pair to plot on a map without guessing.
The GPS sensor is therefore rendered as a normal gauge card today, like every other sensor. The dependency
is ready to use for an actual station map as soon as the backend exposes two coordinate values - per this
module's brief, the backend API is not to be modified or redesigned from the frontend side.

### Sampling Interval (Settings page)

The backend's `GET /system/info` does not currently expose a sampling interval field. The Settings page
displays the **dashboard's own configured refresh interval** (`VITE_REFRESH_INTERVAL_SECONDS`) instead,
clearly labeled "(dashboard refresh)" with a tooltip explaining the distinction - it is not presented as a
backend-reported value.

## State Management

Shared app state uses **React Context** only (`src/context/AppContext.jsx`), exposing the configured API
base URL and refresh interval. No Redux, no other state library. Everything else (fetched data, form
selections, loading/error state) is page-local `useState`/the `usePolling` hook - most of this app's state
genuinely doesn't need to be global.

## Refresh Strategy

Implemented via `src/hooks/usePolling.js`:

- **Dashboard** and **Analytics**: `usePolling(fetchFn, refreshIntervalMs)` - fetches immediately, then
  every `VITE_REFRESH_INTERVAL_SECONDS` (default 5s).
- **Trends**: `usePolling(fetchFn, null, [selectedSensor, selectedRange])` - fetches once on mount and
  again only when the sensor or time-range selection changes; no interval timer runs.
- **Settings**: `usePolling(fetchFn, null)` - fetches once; it's a read-only info page.

No WebSockets, no MQTT, no polling of the Arduino - REST only, per the project brief.

## Error Handling

`src/components/ErrorCard.jsx` renders the five required friendly states:

- **Backend Offline** - the API is unreachable (network-level Axios failure)
- **Database Offline** - reported via `system_health.database_status === "degraded"` on the Dashboard's
  status strip (not a full-page error, since the rest of the API may still work)
- **Serial Disconnected** - reported via `system_health.serial_connection_status` on the Dashboard's status
  strip
- **No Sensor Data** - an empty/`404` result (e.g. no enabled sensors, or an empty history range)
- **Loading** - `src/components/LoadingSpinner.jsx`, shown while the first fetch of a page is in flight

## Testing

```bash
npm run test
```

69 tests across 16 files: every component (`GaugeCard`, `LineChart`, `TrendChart`, `StatusCard`,
`MetricCard`, `SensorTable`, `LoadingSpinner`, `ErrorCard`), every page (`Dashboard`, `Trends`, `Analytics`,
`Settings`, `MainLayout`), the `usePolling` hook, the Axios error normalizer, and `sensorService`'s API
wrapping. Every page/service test mocks `sensorService`/`api` (via `vi.mock`) - the suite never makes a
real network request. `src/test/setup.js` stubs `ResizeObserver` and mocks `echarts` globally (jsdom has no
canvas backend), so chart-backed components render safely and deterministically in tests.

## Performance Notes

- Dashboard/Analytics combine their needed requests into a single `usePolling` fetch function
  (`Promise.all`) per 5-second cycle, rather than several independently-scheduled intervals.
- Trends never polls - it fetches only on an explicit user action, per the refresh strategy above.
- Expensive work (stats computation, ECharts option objects) is wrapped in `useMemo` where it depends on
  fetched data, so it doesn't recompute on every unrelated re-render.
- No client-side caching layer or state library is introduced; at the project's stated scale (~15 sensors,
  5s updates, a single local user) it isn't needed and would be over-engineering.
