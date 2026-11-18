import {
  act,
  fireEvent,
  render as rtlRender,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import SidebarUsage from "./SidebarUsage";
import { tokenUsageApi } from "../api/modules/tokenUsage";

vi.mock("../api/modules/tokenUsage", () => ({
  tokenUsageApi: { getTokenUsage: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "zh" } }),
}));
vi.mock("../components/interaction/InteractiveCard", () => ({
  InteractiveCard: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("./SidebarUsageDialog", () => ({
  default: ({
    open,
    children,
    onCancel,
  }: {
    open: boolean;
    children: ReactNode;
    onCancel: () => void;
  }) =>
    open ? (
      <div role="dialog">
        <button onClick={onCancel}>Close</button>
        {children}
      </div>
    ) : null,
}));
vi.mock("../components/interaction/BottomSheet", () => ({
  default: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? (
      <div role="dialog" aria-label="Sheet">
        {children}
      </div>
    ) : null,
}));
vi.mock("../components/interaction/SnapTrend", () => ({
  SnapTrend: ({ config }: { config: { data: unknown } }) => (
    <output>{JSON.stringify(config.data)}</output>
  ),
}));
const render = (ui: ReactNode) => rtlRender(ui, { wrapper: MemoryRouter });
const getUsage = vi.mocked(tokenUsageApi.getTokenUsage);
const summary = {
  total_prompt_tokens: 120,
  total_completion_tokens: 30,
  by_date: { "2026-09-22": { prompt_tokens: 120, completion_tokens: 30 } },
};
beforeEach(() => getUsage.mockReset());

describe("Sidebar usage", () => {
  it("loads on demand and aggregates real input/output tokens", async () => {
    getUsage.mockResolvedValue(summary as never);
    render(<SidebarUsage mobile={false} agentId="default" />);
    expect(getUsage).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "sidebar.weeklyUsage" }),
    );
    await waitFor(() => expect(screen.getByText("150")).toBeInTheDocument());
    expect(await screen.findByRole("status")).toHaveTextContent('"value":150');
    const { start_date, end_date } = getUsage.mock.calls[0][0];
    expect((Date.parse(end_date) - Date.parse(start_date)) / 86400000).toBe(6);
  });
  it("offers retry after failure and an honest empty state in the mobile sheet", async () => {
    getUsage.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({
      ...summary,
      by_date: {},
      total_prompt_tokens: 0,
      total_completion_tokens: 0,
    } as never);
    render(<SidebarUsage mobile agentId="default" />);
    fireEvent.click(
      screen.getByRole("button", { name: "sidebar.weeklyUsage" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "common.retry" }),
    );
    expect(await screen.findByText("sidebar.noUsage")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Sheet" })).toBeInTheDocument();
  });
  it("discards an old agent response after switching agents", async () => {
    let resolveOld!: (value: never) => void;
    getUsage.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
    );
    getUsage.mockResolvedValueOnce({
      ...summary,
      total_prompt_tokens: 900,
      total_completion_tokens: 100,
    } as never);
    const view = render(<SidebarUsage mobile={false} agentId="first" />);
    fireEvent.click(
      screen.getByRole("button", { name: "sidebar.weeklyUsage" }),
    );
    view.rerender(<SidebarUsage mobile={false} agentId="second" />);
    expect(await screen.findByText("1K")).toBeInTheDocument();
    await act(async () => resolveOld(summary as never));
    expect(screen.queryByText("150")).not.toBeInTheDocument();
    expect(screen.getByText("1K")).toBeInTheDocument();
  });
});

it("filters by provider and model, keeping total and detail navigation", async () => {
  getUsage
    .mockResolvedValueOnce({
      ...summary,
      by_model: {
        "provider-a/Qwen": {
          model: "Qwen",
          provider_id: "provider-a",
          prompt_tokens: 100,
          completion_tokens: 20,
        },
      },
    } as never)
    .mockResolvedValueOnce({
      ...summary,
      by_date: { "2026-09-22": { prompt_tokens: 100, completion_tokens: 20 } },
    } as never);
  render(<SidebarUsage mobile={false} agentId="default" />);
  fireEvent.click(screen.getByRole("button", { name: "sidebar.weeklyUsage" }));
  fireEvent.mouseDown(
    await screen.findByRole("combobox", { name: "sidebar.usageModel" }),
  );
  fireEvent.click(await screen.findByText("Qwen · provider-a"));
  await waitFor(() =>
    expect(getUsage).toHaveBeenLastCalledWith(
      expect.objectContaining({ model: "Qwen", provider: "provider-a" }),
    ),
  );
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent('"value":120'),
  );
  expect(screen.getByText("150")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "sidebar.usageDetails" }),
  ).toHaveAttribute("href", "/settings/token-usage");
});
