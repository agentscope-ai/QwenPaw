import { render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter, type MemoryRouterProps } from "react-router-dom";
import { type ReactNode } from "react";
import { App } from "antd";

interface RenderWithProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  initialEntries?: string[];
}

function AllProviders({
  children,
  routerProps,
}: {
  children: ReactNode;
  routerProps?: MemoryRouterProps;
}) {
  return (
    <App>
      <MemoryRouter {...routerProps}>{children}</MemoryRouter>
    </App>
  );
}

export function renderWithProviders(
  ui: React.ReactElement,
  {
    initialEntries = ["/chat"],
    ...renderOptions
  }: RenderWithProvidersOptions = {},
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <AllProviders routerProps={{ initialEntries }}>{children}</AllProviders>
    );
  }
  return render(ui, { wrapper: Wrapper, ...renderOptions });
}
