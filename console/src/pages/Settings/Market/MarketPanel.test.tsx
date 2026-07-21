// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  installOptions: undefined as
    | { selectedAgent: string; onSuccess?: () => void }
    | undefined,
}));

vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  const Button = ({
    children,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement("button", props, children);
  const Search = (props: InputHTMLAttributes<HTMLInputElement>) =>
    React.createElement("input", props);
  return {
    Button,
    Input: { Search },
    Select: () => null,
    Tooltip: ({ children }: { children: ReactNode }) => children,
  };
});

vi.mock("lucide-react", () => ({ Check: () => null }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: (selector: (state: { selectedAgent: string }) => unknown) =>
    selector({ selectedAgent: "agent-1" }),
}));
vi.mock("./useMarketSearch", () => ({
  useMarketSearch: () => ({
    query: "",
    category: "",
    providers: [],
    selectedProviderKeys: new Set<string>(),
    categories: [],
    results: [],
    errors: [],
    globalError: null,
    loading: false,
    totalCount: 0,
    hasMore: false,
    autoLoadBlocked: false,
    toggleProvider: vi.fn(),
    setCategory: vi.fn(),
    setQuery: vi.fn(),
    retry: vi.fn(),
    loadMore: vi.fn(),
    autoLoadMore: vi.fn(),
  }),
}));
vi.mock("./useMarketInstall", () => ({
  useMarketInstall: (options: {
    selectedAgent: string;
    onSuccess?: () => void;
  }) => {
    hoisted.installOptions = options;
    return {
      queue: [],
      enqueue: vi.fn(),
      clearFinished: vi.fn(),
      cancel: vi.fn(),
      retry: vi.fn(),
    };
  },
}));
vi.mock("./components", () => ({
  ResultCard: () => null,
  DetailDrawer: () => null,
  QueueItem: () => null,
  EmptyState: ({ children }: { children?: ReactNode }) => children ?? null,
}));

import { MarketPanel } from "./MarketPanel";

describe("MarketPanel", () => {
  beforeEach(() => {
    hoisted.installOptions = undefined;
  });

  it("forwards a successful install to its host", () => {
    const onInstalled = vi.fn();

    render(<MarketPanel installTarget="workspace" onInstalled={onInstalled} />);

    expect(hoisted.installOptions?.selectedAgent).toBe("agent-1");
    act(() => hoisted.installOptions?.onSuccess?.());
    expect(onInstalled).toHaveBeenCalledTimes(1);
  });

  it("uses the latest host callback for an in-progress install", () => {
    const firstOnInstalled = vi.fn();
    const latestOnInstalled = vi.fn();
    const { rerender } = render(
      <MarketPanel installTarget="workspace" onInstalled={firstOnInstalled} />,
    );
    const inProgressOnSuccess = hoisted.installOptions?.onSuccess;

    rerender(
      <MarketPanel installTarget="workspace" onInstalled={latestOnInstalled} />,
    );
    act(() => inProgressOnSuccess?.());

    expect(firstOnInstalled).not.toHaveBeenCalled();
    expect(latestOnInstalled).toHaveBeenCalledTimes(1);
  });
});
