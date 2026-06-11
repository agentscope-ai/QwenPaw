import { render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter, type MemoryRouterProps } from "react-router-dom";
import { type ReactNode, createContext, useState } from "react";
import { App } from "antd";
import { TooltipProvider } from "@/components/ui/tooltip";

const ApprovalContext = createContext<{
  approvals: any[];
  setApprovals: (approvals: any[]) => void;
}>({
  approvals: [],
  setApprovals: () => {},
});

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
  const [approvals, setApprovals] = useState<any[]>([]);
  return (
    <ApprovalContext.Provider value={{ approvals, setApprovals }}>
      <App>
        <TooltipProvider>
          <MemoryRouter {...routerProps}>{children}</MemoryRouter>
        </TooltipProvider>
      </App>
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
