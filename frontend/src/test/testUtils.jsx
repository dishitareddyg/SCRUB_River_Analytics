import { render } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { MemoryRouter } from "react-router-dom";
import theme from "../theme/theme";
import { AppProvider } from "../context/AppContext";

/**
 * Render a component wrapped with the same providers the real app
 * uses (MUI theme, app context, router), so components that call
 * `useAppContext()` or router hooks work in tests without every test
 * file re-declaring this boilerplate.
 *
 * @param {React.ReactElement} ui
 * @param {Object} [options]
 * @param {string} [options.route="/"] - Initial router location.
 * @returns {import('@testing-library/react').RenderResult}
 */
export function renderWithProviders(ui, { route = "/" } = {}) {
  return render(
    <ThemeProvider theme={theme}>
      <AppProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </AppProvider>
    </ThemeProvider>
  );
}
