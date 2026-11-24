import { render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter, type MemoryRouterProps } from "react-router-dom";
import { type ReactNode, createContext, useState } from "react";
import { App } from "antd";
import { AuthStatusProvider } from "@/contexts/AuthStatusContext";

const ApprovalContext = createContext<{
  approvals: any[];
  setApprovals: (approvals: any[]) => void;
}>({
  approvals: [],
  setApprovals: () => {},
});

interface RenderWithProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  initialEntries?: MemoryRouterProps["initialEntries"];
}

function AllProviders({
  children,
  routerProps,
}: {
  children: ReactNode;
  routerProps?: MemoryRouterProps;
}) {
  const [approvals, setApprovals] = useState<any[]>([]);
  return (
    <ApprovalContext.Provider value={{ approvals, setApprovals }}>
      <AuthStatusProvider value={{ enabled: false, has_users: false }}>
        <App>
          <MemoryRouter {...routerProps}>{children}</MemoryRouter>
        </App>
      </AuthStatusProvider>
    </ApprovalContext.Provider>
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
