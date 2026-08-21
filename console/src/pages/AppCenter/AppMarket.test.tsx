// @vitest-environment jsdom
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Modal } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { invoke, isTauri } from "@/test/tauri-mock";
import { AppMarket } from "./AppMarket";

const hoisted = vi.hoisted(() => ({
  fetchMarketPlugins: vi.fn(),
  installPlugin: vi.fn(),
  getVersion: vi.fn(),
}));

interface MockIntersectionObserver {
  callback: IntersectionObserverCallback;
  elements: Element[];
}

let intersectionObservers: MockIntersectionObserver[] = [];

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { loading: vi.fn(), success: vi.fn(), error: vi.fn() },
  }),
}));

vi.mock("@/api/modules/pluginMarket", async () => {
  const actual = await vi.importActual<
    typeof import("@/api/modules/pluginMarket")
  >("@/api/modules/pluginMarket");
  return {
    ...actual,
    fetchMarketPlugins: hoisted.fetchMarketPlugins,
  };
});

vi.mock("@/api/modules/plugin", () => ({
  installPlugin: hoisted.installPlugin,
}));

vi.mock("@/api/modules/root", () => ({
  rootApi: { getVersion: hoisted.getVersion },
}));

function makeEntry(
  id: string,
  overrides: Partial<MarketPluginEntry> = {},
): MarketPluginEntry {
  return {
    id,
    display_name: id,
    developer: "dev",
    owner: "owner",
    version: "1.0.0",
    logo_url: null,
    downloads: 42,
    view_count: 10,
    details_url: null,
    locales: { en: { description: `${id} description`, category: "app" } },
    ...overrides,
  };
}

describe("AppMarket", () => {
  const windowOpen = vi.fn();

  beforeEach(() => {
    intersectionObservers = [];
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        private record: MockIntersectionObserver;

        constructor(callback: IntersectionObserverCallback) {
          this.record = { callback, elements: [] };
          intersectionObservers.push(this.record);
        }

        observe(element: Element) {
          this.record.elements.push(element);
        }
        disconnect() {}
      },
    );
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    hoisted.getVersion.mockReset();
    invoke.mockReset();
    invoke.mockResolvedValue(undefined);
    isTauri.mockReturnValue(false);
    windowOpen.mockReset();
    vi.spyOn(window, "open").mockImplementation(windowOpen);
    delete (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
    hoisted.fetchMarketPlugins.mockResolvedValue({ plugins: [], total: 0 });
    hoisted.getVersion.mockResolvedValue({ version: "2.1.0" });
  });

  it("requests featured apps for the official channel", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeEntry("official-app", { is_featured: true })],
      total: 1,
    });

    render(<AppMarket channel="official" onInstalled={vi.fn()} />);

    expect(await screen.findByText("official-app")).toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins).toHaveBeenCalledWith(
      expect.objectContaining({
        page_number: 1,
        page_size: 20,
        is_featured: true,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(
      screen.queryByRole("button", { name: "appCenter.filterAll" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "common.refresh" }),
    ).not.toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins.mock.calls[0][0]).not.toHaveProperty(
      "sort_by",
    );
    expect(screen.getByText("appCenter.featured")).toBeInTheDocument();
  });

  it("shows all apps in the unfiltered app market", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [
        makeEntry("agent-kanban", { is_featured: true }),
        makeEntry("zalo-channel", { is_featured: false }),
        makeEntry("mahjong4"),
      ],
      total: 3,
    });

    render(<AppMarket onInstalled={vi.fn()} />);

    expect(await screen.findByText("zalo-channel")).toBeInTheDocument();
    expect(screen.getByText("mahjong4")).toBeInTheDocument();
    expect(screen.getByText("agent-kanban")).toBeInTheDocument();
    expect(screen.getAllByText("appCenter.featured")).toHaveLength(2);

    const initialParams = hoisted.fetchMarketPlugins.mock.calls[0][0];
    expect(initialParams).not.toHaveProperty("sort_by");
    expect(initialParams).not.toHaveProperty("is_featured");
    expect(initialParams).not.toHaveProperty("is_trending");
  });

  it("passes the selected featured and trending filters to the API", async () => {
    render(<AppMarket onInstalled={vi.fn()} />);
    await screen.findByText("appCenter.marketEmpty");

    fireEvent.click(screen.getByRole("button", { name: "appCenter.featured" }));
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(2),
    );
    expect(hoisted.fetchMarketPlugins.mock.calls[1][0]).toEqual(
      expect.objectContaining({ is_featured: true, page_number: 1 }),
    );

    const trendingButton = screen.getByRole("button", {
      name: "appCenter.trending",
    });
    await waitFor(() => expect(trendingButton).toBeEnabled());
    fireEvent.click(trendingButton);
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(3),
    );
    expect(hoisted.fetchMarketPlugins.mock.calls[2][0]).toEqual(
      expect.objectContaining({ is_trending: true, page_number: 1 }),
    );
    expect(hoisted.fetchMarketPlugins.mock.calls[2][0]).not.toHaveProperty(
      "is_featured",
    );
  });

  it("refreshes page one with the current market filter", async () => {
    render(<AppMarket onInstalled={vi.fn()} />);
    await screen.findByText("appCenter.marketEmpty");

    fireEvent.click(screen.getByRole("button", { name: "appCenter.featured" }));
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(2),
    );

    const refreshButton = screen.getByRole("button", {
      name: "common.refresh",
    });
    await waitFor(() => expect(refreshButton).toBeEnabled());
    fireEvent.click(refreshButton);

    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(3),
    );
    expect(hoisted.fetchMarketPlugins.mock.calls[2][0]).toEqual(
      expect.objectContaining({
        page_number: 1,
        is_featured: true,
      }),
    );
    expect(hoisted.fetchMarketPlugins.mock.calls[2][0]).not.toHaveProperty(
      "sort_by",
    );
  });

  it("loads and appends the next market page when the sentinel is visible", async () => {
    const firstPage = Array.from({ length: 20 }, (_, index) =>
      makeEntry(`community-${index}`),
    );
    hoisted.fetchMarketPlugins.mockImplementation(({ page_number }) =>
      Promise.resolve(
        page_number === 1
          ? { plugins: firstPage, total: 21 }
          : {
              plugins: [makeEntry("community-page-two")],
              total: 21,
            },
      ),
    );

    render(<AppMarket onInstalled={vi.fn()} />);

    expect(await screen.findByText("community-0")).toBeInTheDocument();
    expect(screen.queryByText("community-page-two")).not.toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1);

    const sentinel = await screen.findByText("common.loading");
    const sentinelObserver = intersectionObservers.find((observer) =>
      observer.elements.includes(sentinel),
    );
    expect(sentinelObserver).toBeDefined();
    act(() => {
      sentinelObserver!.callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });

    expect(await screen.findByText("community-page-two")).toBeInTheDocument();
    expect(screen.getByText("community-0")).toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(2);
    expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page_number: 2,
        page_size: 20,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(hoisted.fetchMarketPlugins.mock.calls[1][0]).not.toHaveProperty(
      "sort_by",
    );
    expect(screen.getByText("appCenter.noMoreApps")).toBeInTheDocument();
  });

  it("aborts an obsolete request when a new search starts", async () => {
    let staleSignal: AbortSignal | undefined;
    hoisted.fetchMarketPlugins
      .mockResolvedValueOnce({ plugins: [], total: 0 })
      .mockImplementationOnce((_params, options) => {
        staleSignal = options?.signal;
        return new Promise((_resolve, reject) => {
          staleSignal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        });
      })
      .mockResolvedValueOnce({
        plugins: [makeEntry("latest-result")],
        total: 1,
      });

    render(<AppMarket onInstalled={vi.fn()} />);
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );

    const search = screen.getByRole("textbox", {
      name: "appCenter.searchMarket",
    });
    fireEvent.change(search, { target: { value: "stale" } });
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() => expect(staleSignal).toBeDefined());

    fireEvent.change(search, { target: { value: "" } });

    expect(await screen.findByText("latest-result")).toBeInTheDocument();
    expect(staleSignal?.aborted).toBe(true);
  });

  it("renders community apps in a single grid", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [
        makeEntry("regular-app"),
        makeEntry("another-app", { is_featured: false }),
      ],
      total: 2,
    });

    const { container } = render(<AppMarket onInstalled={vi.fn()} />);

    await screen.findByText("regular-app");
    const grids = container.querySelectorAll("[class*='grid']");
    expect(grids).toHaveLength(1);

    const titles = Array.from(
      container.querySelectorAll("[class*='cardTitle']"),
    ).map((el) => el.textContent);
    expect(titles).toEqual(["regular-app", "another-app"]);
  });

  it("does not render the emoji download glyph", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeEntry("some-app")],
      total: 1,
    });

    render(<AppMarket onInstalled={vi.fn()} />);

    await screen.findByText("some-app");
    expect(document.body.textContent).not.toContain("⬇");
  });

  it("installs an app and notifies the parent to refresh", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeEntry("installable")],
      total: 1,
    });
    const installResult = { id: "installable", name: "installable" };
    hoisted.installPlugin.mockResolvedValue(installResult);
    const onInstalled = vi.fn();

    render(<AppMarket onInstalled={onInstalled} />);

    fireEvent.click(await screen.findByText("appCenter.install"));

    await waitFor(() =>
      expect(onInstalled).toHaveBeenCalledWith(installResult),
    );
    expect(hoisted.installPlugin).toHaveBeenCalledTimes(1);
  });

  it("disables repeat installs while an install is in flight", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeEntry("slow-install")],
      total: 1,
    });
    hoisted.installPlugin.mockReturnValue(new Promise(() => {}));

    render(<AppMarket onInstalled={vi.fn()} />);

    const installBtn = await screen.findByText("appCenter.install");
    fireEvent.click(installBtn);
    await screen.findByText("appCenter.installing");
    fireEvent.click(screen.getByText("appCenter.installing"));

    expect(hoisted.installPlugin).toHaveBeenCalledTimes(1);
  });

  it("disables other apps while an install is in flight", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeEntry("first-app"), makeEntry("second-app")],
      total: 2,
    });
    hoisted.installPlugin.mockReturnValue(new Promise(() => {}));

    render(<AppMarket onInstalled={vi.fn()} />);

    const installButtons = await screen.findAllByRole("button", {
      name: "appCenter.install",
    });
    fireEvent.click(installButtons[0]);

    await waitFor(() => expect(installButtons[1]).toBeDisabled());
    fireEvent.click(installButtons[1]);
    expect(hoisted.installPlugin).toHaveBeenCalledTimes(1);
  });

  it("asks for confirmation before installing an incompatible app", async () => {
    hoisted.getVersion.mockResolvedValue({ version: "1.9.0" });
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeEntry("future-app", { qwenpaw_compat_labels: ["2.x"] })],
      total: 1,
    });
    hoisted.installPlugin.mockResolvedValue({ name: "future-app" });
    const confirmSpy = vi
      .spyOn(Modal, "confirm")
      .mockReturnValue({ destroy: vi.fn(), update: vi.fn() });

    render(<AppMarket onInstalled={vi.fn()} />);

    await waitFor(() => expect(hoisted.getVersion).toHaveBeenCalled());
    fireEvent.click(
      await screen.findByRole("button", { name: "appCenter.install" }),
    );

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(hoisted.installPlugin).not.toHaveBeenCalled();

    const confirmOptions = confirmSpy.mock.calls[0][0];
    await confirmOptions.onOk?.();
    await waitFor(() => expect(hoisted.installPlugin).toHaveBeenCalledTimes(1));
  });

  it("opens details through the shared external-link guard", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [
        makeEntry("with-details", {
          details_url: "https://platform.agentscope.io/apps/demo",
        }),
      ],
      total: 1,
    });

    render(<AppMarket onInstalled={vi.fn()} />);

    fireEvent.click(await screen.findByText("appCenter.details"));

    expect(windowOpen).toHaveBeenCalledWith(
      "https://platform.agentscope.io/apps/demo",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("does not open unsupported details URL schemes", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [
        makeEntry("evil-details", { details_url: "javascript:alert(1)" }),
      ],
      total: 1,
    });

    render(<AppMarket onInstalled={vi.fn()} />);

    fireEvent.click(await screen.findByText("appCenter.details"));

    expect(windowOpen).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalled();
  });

  it("shows the market error inside the market view", async () => {
    hoisted.fetchMarketPlugins.mockRejectedValue(new Error("boom"));

    render(<AppMarket onInstalled={vi.fn()} />);

    expect(
      await screen.findByText("pluginManager.marketUnavailable"),
    ).toBeInTheDocument();
  });
});
