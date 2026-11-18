import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLocation, useNavigate } from "react-router-dom";
import WindowRouter from "./WindowRouter";
import { useOsRoute } from "./osRouteStore";
import { useOsWindows } from "./osWindowStore";

const hoisted = vi.hoisted(() => ({ routeSnapshot: vi.fn() }));

vi.mock("../plugins/registry/hooks", () => ({
  useRoutes: () => hoisted.routeSnapshot(),
}));

/** Registry routes used by pathToRouteId to decide who owns a pathname. */
const ROUTES = [
  { id: "core.chat", path: "/chat/*" },
  { id: "core.models", path: "/models" },
  { id: "core.inbox", path: "/inbox" },
];

/** Stands in for the page component a real window would host. */
function PageProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <div>
      <output data-testid="path">{location.pathname + location.search}</output>
      <button onClick={() => navigate("/chat/session-9?tab=x")}>
        go-session
      </button>
      <button onClick={() => navigate("/models")}>go-models</button>
      <button onClick={() => navigate("/elsewhere")}>go-elsewhere</button>
    </div>
  );
}

function renderWindow(routeId = "core.chat", base = "/chat") {
  return render(
    <WindowRouter routeId={routeId} base={base} element={<PageProbe />} />,
  );
}

describe("WindowRouter", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", {
      value: 1440,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 900,
      configurable: true,
      writable: true,
    });
    hoisted.routeSnapshot.mockReturnValue(ROUTES);
    useOsRoute.setState({ targets: {}, navigateTo: vi.fn() });
    useOsWindows.setState({
      windows: {},
      order: [],
      activeId: null,
      zCounter: 100,
      launcherOpen: false,
      spaceId: "default",
      saved: {},
      missionControlOpen: false,
    });
  });

  it("seeds the window router at the app base and keeps intra-app navigation local", () => {
    renderWindow();

    expect(screen.getByTestId("path")).toHaveTextContent("/chat");

    fireEvent.click(screen.getByText("go-session"));
    expect(screen.getByTestId("path")).toHaveTextContent(
      "/chat/session-9?tab=x",
    );
    // Staying inside this app must never be handed to the OS route store.
    expect(useOsRoute.getState().navigateTo).not.toHaveBeenCalled();
  });

  it("redirects a pathname no app owns back to this window's base", async () => {
    renderWindow();

    fireEvent.click(screen.getByText("go-elsewhere"));

    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toBe("/chat"),
    );
    expect(useOsRoute.getState().navigateTo).not.toHaveBeenCalled();
  });

  it("navigates to a deep-link target already pending when the window opens", () => {
    useOsRoute.setState({
      targets: { "core.chat": { path: "/chat/session-1", nonce: 1 } },
    });

    renderWindow();

    expect(screen.getByTestId("path")).toHaveTextContent("/chat/session-1");
  });

  it("follows a deep-link target posted while the window is open", () => {
    renderWindow();
    expect(screen.getByTestId("path")).toHaveTextContent("/chat");

    act(() => {
      useOsRoute.setState({
        targets: { "core.chat": { path: "/chat/session-2", nonce: 1 } },
      });
    });

    expect(screen.getByTestId("path")).toHaveTextContent("/chat/session-2");
  });

  it("re-fires the same deep-link path when its nonce is bumped", () => {
    renderWindow();
    act(() => {
      useOsRoute.setState({
        targets: { "core.chat": { path: "/chat/session-2", nonce: 1 } },
      });
    });
    expect(screen.getByTestId("path")).toHaveTextContent("/chat/session-2");

    // The user moves on inside the window:
    fireEvent.click(screen.getByText("go-session"));
    expect(screen.getByTestId("path")).toHaveTextContent(
      "/chat/session-9?tab=x",
    );

    // then the very same target is re-posted with a fresh nonce.
    act(() => {
      useOsRoute.setState({
        targets: { "core.chat": { path: "/chat/session-2", nonce: 2 } },
      });
    });

    expect(screen.getByTestId("path")).toHaveTextContent("/chat/session-2");
  });

  it("hands a cross-app navigation to the OS route store and stays inside this app", async () => {
    renderWindow();

    // Own-app navigation first, so the bridge records a location to return to.
    fireEvent.click(screen.getByText("go-session"));
    expect(screen.getByTestId("path")).toHaveTextContent(
      "/chat/session-9?tab=x",
    );

    fireEvent.click(screen.getByText("go-models"));

    // The foreign path is handed to the OS so it can open that app's window.
    await waitFor(() =>
      expect(useOsRoute.getState().navigateTo).toHaveBeenCalledWith(
        "core.models",
        "/models",
      ),
    );
    expect(useOsRoute.getState().navigateTo).toHaveBeenCalledOnce();
    // This window must not be left showing another app's path. Which own-app
    // location it lands on is left open on purpose: the bridge restores the
    // last own-app location while the catch-all route falls back to the base.
    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toMatch(/^\/chat/),
    );
  });
});
