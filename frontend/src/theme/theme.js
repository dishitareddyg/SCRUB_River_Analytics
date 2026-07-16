import { createTheme } from "@mui/material/styles";

/**
 * A clean, low-saturation "industrial control room" palette:
 * dark slate surfaces, a single confident accent (cyan), and
 * status colors reserved strictly for status (green/amber/red).
 */
const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#38bdf8", // sky blue - the one accent color used throughout
      light: "#7dd3fc",
      dark: "#0284c7",
      contrastText: "#0b1220",
    },
    secondary: {
      main: "#94a3b8",
    },
    background: {
      default: "#0b1220",
      paper: "#111a2b",
    },
    text: {
      primary: "#e2e8f0",
      secondary: "#94a3b8",
    },
    success: { main: "#22c55e" },
    warning: { main: "#f59e0b" },
    error: { main: "#ef4444" },
    info: { main: "#38bdf8" },
    divider: "rgba(148, 163, 184, 0.16)",
  },
  shape: {
    borderRadius: 10,
  },
  typography: {
    fontFamily: [
      "Inter",
      "Roboto",
      "Segoe UI",
      "Helvetica Neue",
      "Arial",
      "sans-serif",
    ].join(","),
    h4: { fontWeight: 600, letterSpacing: -0.5 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    subtitle2: { fontWeight: 500, color: "#94a3b8" },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          border: "1px solid rgba(148, 163, 184, 0.12)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          border: "1px solid rgba(148, 163, 184, 0.12)",
        },
      },
    },
    MuiButtonBase: {
      defaultProps: {
        disableRipple: true,
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 600,
        },
      },
    },
  },
});

export default theme;
