import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
const mocks = vi.hoisted(() => ({
  setFocusItemIds: vi.fn(),
  setSidebarItemsVisible: vi.fn(),
  resetFocusItemIds: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) =>
      options?.name ? `${key} ${options.name}` : key,
  }),
}));
vi.mock("@/stores/sidebarStore", () => ({
  useSidebarStore: () => ({
    focusItemIds: ["core.tools", "unavailable.plugin"],
    hiddenPluginItemIds: ["plugin.extra"],
    ...mocks,
  }),
}));
vi.mock("./useSidebarEntryGroups", () => ({
  useSidebarEntryGroups: () => ({
    work: [
      { key: "core.tools", label: "Tools" },
      { key: "core.files", label: "Files" },
    ],
    global: [],
    plugins: [{ key: "plugin.extra", label: "Extra" }],
  }),
}));
import NavigationSettings from "./NavigationSettings";
beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});
describe("sidebar entry editing", () => {
  it("autosaves after one idle second without losing unavailable entries", async () => {
    renderWithProviders(<NavigationSettings />);
    fireEvent.click(screen.getByRole("button", { name: "common.edit" }));
    fireEvent.click(
      screen.getByRole("button", { name: "settingsCenter.addEntry Files" }),
    );
    expect(mocks.setFocusItemIds).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(999);
    });
    expect(mocks.setFocusItemIds).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(mocks.setFocusItemIds).toHaveBeenCalledWith([
      "core.tools",
      "core.files",
      "unavailable.plugin",
    ]);
  });
  it("flushes plugin visibility changes when leaving the page", async () => {
    const { unmount } = renderWithProviders(<NavigationSettings />);
    fireEvent.click(screen.getByRole("button", { name: "common.edit" }));
    fireEvent.click(
      screen.getByRole("button", { name: "settingsCenter.addEntry Extra" }),
    );
    await act(async () => {
      unmount();
    });
    expect(mocks.setSidebarItemsVisible).toHaveBeenCalledWith(
      ["plugin.extra"],
      true,
    );
    expect(mocks.setFocusItemIds).toHaveBeenCalledWith([
      "core.tools",
      "plugin.extra",
      "unavailable.plugin",
    ]);
  });
  it("finishes editing after saving and keeps Inbox fixed", async () => {
    renderWithProviders(<NavigationSettings />);
    fireEvent.click(screen.getByRole("button", { name: "common.edit" }));
    expect(
      screen.queryByRole("button", {
        name: "settingsCenter.removeEntry nav.inbox",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "settingsCenter.removeEntry Tools" }),
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "common.done" }));
    });
    expect(mocks.setFocusItemIds).toHaveBeenCalledWith(["unavailable.plugin"]);
    expect(screen.getByRole("button", { name: "common.edit" })).toBeVisible();
  });
});
