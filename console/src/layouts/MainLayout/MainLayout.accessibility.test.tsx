// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import MainLayout from ".";

const routeControl = vi.hoisted(() => ({
  suspended: false,
  promise: Promise.resolve() as Promise<void>,
}));

vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: vi.fn() },
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../Sidebar", () => ({ default: () => <aside>Sidebar</aside> }));
vi.mock("../AmbientLight", () => ({ default: () => null }));
vi.mock("../Header", () => ({ default: () => <header>Header</header> }));
vi.mock("../../components/ConsolePollService", () => ({
  default: () => null,
}));
vi.mock("../../components/AgentStatusPollingController", () => ({
  AgentStatusPollingController: () => null,
}));
vi.mock("../../stores/useSyncCodingMode", () => ({
  useSyncCodingMode: () => undefined,
}));
vi.mock("../../plugins/registry/hooks", async () => {
  const { BUILTIN_ROUTES } = await vi.importActual<
    typeof import("../registry/builtinRoutes")
  >("../registry/builtinRoutes");
  const acpRoute = BUILTIN_ROUTES.find(({ id }) => id === "core.acp");
  const acpAliasRoute = BUILTIN_ROUTES.find(
    ({ id }) => id === "core.acp-alias",
  );
  if (!acpRoute || !acpAliasRoute) throw new Error("ACP routes are required");

  return {
    useRoutes: () => [
      {
        id: "core.chat",
        path: "/chat",
        Component: () => {
          if (routeControl.suspended) {
            throw routeControl.promise;
          }

          return <div>Chat route</div>;
        },
      },
      {
        id: "test.origin",
        path: "/origin",
        Component: () => <div>Origin page</div>,
      },
      {
        id: "core.acp",
        path: "/acp",
        caseSensitive: acpRoute.caseSensitive,
        Component: () => <div>ACP page</div>,
      },
      {
        id: "core.acp-alias",
        path: "/ACP",
        Component: acpAliasRoute.component,
      },
    ],
  };
});
vi.mock("../../plugins/registry/Slot", () => ({ Slot: () => null }));
vi.mock("../../components/PageShell", () => ({
  PageShell: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("./RouteDocumentTitle", () => ({
  RouteDocumentTitle: () => null,
}));

function HistoryControls() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <>
      <output data-testid="pathname">{location.pathname}</output>
      <output data-testid="search">{location.search}</output>
      <output data-testid="hash">{location.hash}</output>
      <button type="button" onClick={() => navigate(-1)}>
        Back
      </button>
      <button type="button" onClick={() => navigate(1)}>
        Forward
      </button>
    </>
  );
}

describe("MainLayout accessibility", () => {
  afterEach(() => {
    routeControl.suspended = false;
    routeControl.promise = Promise.resolve();
  });

  it("moves focus from the skip link to the main content", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <MainLayout />
      </MemoryRouter>,
    );

    await user.tab();
    const skipLink = screen.getByRole("link", { name: "Skip to content" });
    expect(skipLink).toHaveFocus();
    expect(skipLink).toHaveAttribute("href", "#main-content");

    await user.keyboard("{Enter}");
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("keeps the route loading fallback local and accessible", async () => {
    const user = userEvent.setup();
    let resolveRoute = () => undefined;
    routeControl.suspended = true;
    routeControl.promise = new Promise<void>((resolve) => {
      resolveRoute = () => {
        routeControl.suspended = false;
        resolve();
      };
    });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <MainLayout />
      </MemoryRouter>,
    );

    const main = screen.getByRole("main");
    const spinner = screen.getByLabelText("common.loading");
    expect(main).toContainElement(spinner);

    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(main).toHaveFocus();

    await act(async () => resolveRoute());

    expect(await screen.findByText("Chat route")).toBeInTheDocument();
    expect(screen.queryByLabelText("common.loading")).not.toBeInTheDocument();
  });

  it("replaces the uppercase ACP alias with the canonical route", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter
        initialEntries={["/origin", "/ACP?source=external#section"]}
        initialIndex={1}
      >
        <HistoryControls />
        <MainLayout />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent("/acp");
    });
    expect(screen.getByTestId("search")).toHaveTextContent("?source=external");
    expect(screen.getByTestId("hash")).toHaveTextContent("#section");
    expect(screen.getByText("ACP page")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent("/origin");
    });
    expect(screen.getByTestId("search")).toBeEmptyDOMElement();
    expect(screen.getByTestId("hash")).toBeEmptyDOMElement();

    await user.click(screen.getByRole("button", { name: "Forward" }));
    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent("/acp");
    });
    expect(screen.getByTestId("search")).toHaveTextContent("?source=external");
    expect(screen.getByTestId("hash")).toHaveTextContent("#section");
  });

  it("keeps the canonical ACP route stable", () => {
    render(
      <MemoryRouter initialEntries={["/acp"]}>
        <HistoryControls />
        <MainLayout />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("pathname")).toHaveTextContent("/acp");
    expect(screen.getByText("ACP page")).toBeInTheDocument();
  });
});
