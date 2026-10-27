/**
 * Unit tests for the PawApps settings page: the installed app list, the detail
 * pane of the selected app and the iframe that hosts its frontend.
 *
 * Facts that shaped this suite (each one read off the source or measured):
 *
 * 1. antd renders for real here (`Card, Empty, Spin, Button, Tag, Typography,
 *    Space`), so the app cards, the tags and the three empty-state
 *    descriptions are the genuine article and are queried by text/role. The
 *    card's selected state is a hashed CSS-module class, so "which card is
 *    selected" is asserted through the detail pane instead, which is the part
 *    the user actually reads.
 * 2. `PageHeader` is rendered for real (it has no external dependencies), so the
 *    refresh button lives inside the header's `extra` slot and is found by its
 *    accessible label.
 * 3. `../../../plugins/PawAppAccessGate` is mocked. The real gate awaits a
 *    native browser session before rendering children, so it would hold the
 *    iframe behind a spinner forever in jsdom. The double renders children and
 *    exposes the `appId` it was given, which keeps two contracts assertable:
 *    the iframe is wrapped in the gate, and the gate is re-keyed per app.
 * 4. `../../../api/modules/pawapp` is mocked, including `getStaticUrl`, because
 *    the iframe `src` is built from it. Asserting the arguments it receives is
 *    the frontend contract ("the iframe points at this app's static asset"),
 *    not a statement about the backend.
 * 5. `window.open` is stubbed per test so the "open in new tab" action can be
 *    asserted without touching a real browser. The built path uses
 *    `encodeURIComponent(app.id)`, so an id needing encoding is part of the
 *    fixture.
 * 6. The auto-select rule is `if (!selectedApp && data.apps.length > 0)`, i.e.
 *    it only fires while nothing is selected. That makes "a refresh keeps the
 *    current selection even if the server reorders the list" a real contract,
 *    and it is asserted below rather than assumed.
 * 7. On a failed fetch the component logs and falls through to `loading: false`
 *    with the previous (empty) list, so the user sees the "no apps" state. The
 *    console error is spied on so the run stays quiet.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import React from "react";
import type { PawAppInfo } from "@/api/modules/pawapp";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  getStaticUrl: vi.fn(),
}));

const errorSpy = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("react-i18next", () => ({
  // This page calls `t(key, fallback)`; asserting on the key keeps every
  // expectation independent of locale files.
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
  }),
}));

vi.mock("../../../api/modules/pawapp", () => ({
  pawappApi: {
    list: api.list,
    getStaticUrl: api.getStaticUrl,
  },
}));

vi.mock("../../../plugins/PawAppAccessGate", () => ({
  // Test double on purpose (see note 3).
  PawAppAccessGate: (props: { appId: string; children?: React.ReactNode }) => (
    <div data-testid="access-gate" data-app-id={props.appId}>
      {props.children}
    </div>
  ),
}));

import PawAppsPage from "./index";

function makeApp(id: string, overrides: Partial<PawAppInfo> = {}): PawAppInfo {
  return {
    id,
    name: `App ${id}`,
    version: `1.${id}.0`,
    description: `Description for ${id}`,
    author: `Author ${id}`,
    category: `cat-${id}`,
    icon: "icon.png",
    status: "installed",
    home_page: "index.html",
    dir: `/root/.copaw/apps/${id}`,
    settings: [],
    permissions: {},
    backends: {},
    ...overrides,
  } as PawAppInfo;
}

const TWO_APPS = [makeApp("alpha"), makeApp("beta", { home_page: null })];

function stubStaticUrl() {
  api.getStaticUrl.mockImplementation(
    (appId: string, filePath: string) =>
      `/api/pawapps/${appId}/static/${filePath}`,
  );
}

async function renderPage() {
  render(<PawAppsPage />);
  // Flush the mount effect's promise chain.
  await waitFor(() => expect(api.list).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.queryAllByRole("button")).not.toHaveLength(0),
  );
}

function refreshButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "common.refresh" });
}

/**
 * The app cards in list order. Scoped through antd's own Card root class
 * rather than by text, because the detail pane renders the selected app's name
 * a second time and a document-wide text query would find two matches.
 */
function appCards(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(".ant-card"));
}

beforeEach(() => {
  api.list.mockReset();
  api.getStaticUrl.mockReset();
  stubStaticUrl();
  api.list.mockResolvedValue({ apps: TWO_APPS, total: TWO_APPS.length });
  errorSpy.current = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  (errorSpy.current as ReturnType<typeof vi.spyOn>).mockRestore();
});

describe("PawApps page - loading and empty", () => {
  it("shows neither the app list nor an empty state while loading", async () => {
    let release: (value: { apps: PawAppInfo[]; total: number }) => void = () =>
      undefined;
    api.list.mockReturnValue(
      new Promise<{ apps: PawAppInfo[]; total: number }>((resolve) => {
        release = resolve;
      }),
    );
    render(<PawAppsPage />);
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(1));
    // Still pending: the pane must not claim "no apps installed".
    expect(screen.queryByText("pawapps.noApps")).toBeNull();
    expect(screen.queryByText("App alpha")).toBeNull();

    release({ apps: TWO_APPS, total: 2 });
    // alpha is auto-selected, so its name shows in both the card and the
    // detail pane; assert on the card count rather than a single text match.
    await waitFor(() => expect(appCards()).toHaveLength(2));
    await waitFor(() =>
      expect(
        screen.getByTestId("access-gate").getAttribute("data-app-id"),
      ).toBe("alpha"),
    );
  });

  it("says no apps are installed when the catalog is empty", async () => {
    api.list.mockResolvedValue({ apps: [], total: 0 });
    await renderPage();
    expect(screen.getByText("pawapps.noApps")).toBeTruthy();
    // No detail pane at all in the empty state.
    expect(screen.queryByTestId("access-gate")).toBeNull();
  });

  it("logs and falls back to the empty state when listing fails", async () => {
    api.list.mockRejectedValue(new Error("boom"));
    await renderPage();
    expect(errorSpy.current).toHaveBeenCalled();
    expect(screen.getByText("pawapps.noApps")).toBeTruthy();
  });
});

describe("PawApps page - app list", () => {
  it("renders one card per app with name, version, description and category", async () => {
    await renderPage();
    const cards = appCards();
    expect(cards).toHaveLength(2);
    // Both the name and the version also appear in the detail pane for the
    // selected app, so these are read inside their own card.
    expect(within(cards[0]).getByText("App alpha")).toBeTruthy();
    expect(within(cards[0]).getByText("v1.alpha.0")).toBeTruthy();
    expect(within(cards[0]).getByText("Description for alpha")).toBeTruthy();
    expect(within(cards[0]).getByText("cat-alpha")).toBeTruthy();
    expect(within(cards[1]).getByText("App beta")).toBeTruthy();
    expect(within(cards[1]).getByText("cat-beta")).toBeTruthy();
  });

  it("falls back to a plain description when the app has none", async () => {
    api.list.mockResolvedValue({
      apps: [makeApp("gamma", { description: "", category: "" })],
      total: 1,
    });
    await renderPage();
    expect(screen.getByText("No description")).toBeTruthy();
    // An empty category renders no tag at all.
    expect(screen.queryByText("cat-gamma")).toBeNull();
  });

  it("omits the category tag when the app has no category", async () => {
    api.list.mockResolvedValue({
      apps: [makeApp("delta", { category: "" })],
      total: 1,
    });
    await renderPage();
    expect(screen.queryByText("cat-delta")).toBeNull();
    expect(screen.getByText("Description for delta")).toBeTruthy();
  });
});

describe("PawApps page - auto selection", () => {
  it("selects the first app on load and hosts its frontend in the gate", async () => {
    await renderPage();
    const gate = screen.getByTestId("access-gate");
    expect(gate.getAttribute("data-app-id")).toBe("alpha");
    const iframe = within(gate).getByTitle("App alpha") as HTMLIFrameElement;
    expect(iframe.tagName).toBe("IFRAME");
    expect(iframe.getAttribute("src")).toBe(
      "/api/pawapps/alpha/static/index.html",
    );
    expect(api.getStaticUrl).toHaveBeenCalledWith("alpha", "index.html");
  });

  it("switches the detail pane when another card is clicked", async () => {
    api.list.mockResolvedValue({
      apps: [makeApp("alpha"), makeApp("beta")],
      total: 2,
    });
    await renderPage();
    expect(screen.getByTestId("access-gate").getAttribute("data-app-id")).toBe(
      "alpha",
    );

    fireEvent.click(screen.getByText("App beta"));
    await waitFor(() =>
      expect(
        screen.getByTestId("access-gate").getAttribute("data-app-id"),
      ).toBe("beta"),
    );
    expect(api.getStaticUrl).toHaveBeenLastCalledWith("beta", "index.html");
  });

  it("keeps the current selection across a refresh that reorders the list", async () => {
    // Both apps need a frontend here: beta has home_page null in the shared
    // fixture, which would put the detail pane in its "no UI" branch instead
    // of the gate this case asserts on.
    const alpha = makeApp("alpha");
    const beta = makeApp("beta");
    api.list.mockResolvedValue({ apps: [alpha, beta], total: 2 });
    await renderPage();
    expect(screen.getByTestId("access-gate").getAttribute("data-app-id")).toBe(
      "alpha",
    );

    fireEvent.click(screen.getByText("App beta"));
    await waitFor(() =>
      expect(
        screen.getByTestId("access-gate").getAttribute("data-app-id"),
      ).toBe("beta"),
    );

    // Server now returns the apps in the opposite order.
    api.list.mockResolvedValue({ apps: [beta, alpha], total: 2 });
    fireEvent.click(refreshButton());
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(appCards()).toHaveLength(2));

    // The auto-select guard only fires while nothing is selected, so the pane
    // must still show beta rather than the new first entry.
    expect(screen.getByTestId("access-gate").getAttribute("data-app-id")).toBe(
      "beta",
    );
  });
});

describe("PawApps page - app without a frontend", () => {
  it("says the app has no UI and renders no iframe", async () => {
    api.list.mockResolvedValue({
      apps: [makeApp("epsilon", { home_page: null })],
      total: 1,
    });
    await renderPage();
    expect(screen.getByText("pawapps.noUI")).toBeTruthy();
    expect(screen.queryByTestId("access-gate")).toBeNull();
    expect(screen.queryByTitle("App epsilon")).toBeNull();
    // No frontend means no "open in new tab" affordance either.
    expect(screen.queryByText("pawapps.openInNewTab")).toBeNull();
  });

  it("passes an empty src to the iframe when no static url can be built", async () => {
    api.getStaticUrl.mockReturnValue(undefined as unknown as string);
    await renderPage();
    const iframe = screen.getByTitle("App alpha") as HTMLIFrameElement;
    expect(iframe.getAttribute("src")).toBe("");
  });
});

describe("PawApps page - open in new tab", () => {
  it("opens the app-scoped path in a new tab", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    await renderPage();
    fireEvent.click(screen.getByText("pawapps.openInNewTab"));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("/apps/alpha", "_blank");
    openSpy.mockRestore();
  });

  it("percent-encodes an app id that needs it", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    api.list.mockResolvedValue({
      apps: [makeApp("my app/x", { name: "Odd Id" })],
      total: 1,
    });
    await renderPage();
    fireEvent.click(screen.getByText("pawapps.openInNewTab"));
    expect(openSpy).toHaveBeenCalledWith("/apps/my%20app%2Fx", "_blank");
    openSpy.mockRestore();
  });
});

describe("PawApps page - refresh", () => {
  it("lists the apps again when the header refresh is clicked", async () => {
    await renderPage();
    expect(api.list).toHaveBeenCalledTimes(1);
    fireEvent.click(refreshButton());
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });

  it("picks up an app that appeared after a refresh", async () => {
    api.list.mockResolvedValue({ apps: [], total: 0 });
    await renderPage();
    expect(screen.getByText("pawapps.noApps")).toBeTruthy();

    api.list.mockResolvedValue({ apps: [makeApp("zeta")], total: 1 });
    fireEvent.click(refreshButton());
    // zeta is auto-selected, so its name shows in both the card and the detail
    // pane; assert on the card count rather than a single text match.
    await waitFor(() => expect(appCards()).toHaveLength(1));
    await waitFor(() =>
      expect(within(appCards()[0]).getByText("App zeta")).toBeTruthy(),
    );
    // Nothing was selected before, so the auto-select guard fires now.
    expect(screen.getByTestId("access-gate").getAttribute("data-app-id")).toBe(
      "zeta",
    );
  });
});
