import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CreatorBackendBlockingOverlay,
  CreatorBackendNotReadyPage,
} from "@/components/system/CreatorBackendStatus";
import { reportBackendAvailable } from "@/lib/backendHealthSignal";
import { useCreatorBackendHealthStore } from "@/store/creatorBackendHealthStore";

function resetHealth(): void {
  reportBackendAvailable();
  useCreatorBackendHealthStore.setState({
    phase: "checking",
    probing: false,
    everReady: false,
    error: null,
    checkedAt: null,
  });
}

function stubHealthyFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    ),
  );
}

describe("Creator backend status surfaces", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    resetHealth();
  });

  afterEach(() => {
    // Unmount before resetting the shared store so the reset cannot update a
    // still-mounted component outside act().
    cleanup();
    vi.unstubAllGlobals();
    resetHealth();
  });

  it("takes over the page with a diagnosis and re-probes from retry", async () => {
    useCreatorBackendHealthStore.setState({
      phase: "unavailable",
      error: "HTTP 405 Method Not Allowed",
      checkedAt: "2026-11-17T00:00:00.000Z",
    });
    stubHealthyFetch();

    render(<CreatorBackendNotReadyPage />);

    const page = document.querySelector("[data-creator-backend-not-ready]");
    expect(page).not.toBeNull();
    expect(page).toHaveTextContent("Creator 服务未就绪");
    expect(page).toHaveTextContent("HTTP 405 Method Not Allowed");

    fireEvent.click(
      document.querySelector("[data-backend-retry]") as HTMLButtonElement,
    );
    await waitFor(() =>
      expect(useCreatorBackendHealthStore.getState().phase).toBe("ready"),
    );
    expect(useCreatorBackendHealthStore.getState().everReady).toBe(true);
  });

  it("keeps the page in the unavailable state while a retry probe runs", async () => {
    useCreatorBackendHealthStore.setState({
      phase: "unavailable",
      error: "HTTP 405 Method Not Allowed",
      checkedAt: "2026-11-17T00:00:00.000Z",
    });
    let finish!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      ),
    );

    render(<CreatorBackendNotReadyPage />);
    fireEvent.click(
      document.querySelector("[data-backend-retry]") as HTMLButtonElement,
    );

    // A re-probe must not unmount the takeover page: the last known phase
    // stays until the probe actually succeeds.
    expect(useCreatorBackendHealthStore.getState().phase).toBe("unavailable");
    expect(useCreatorBackendHealthStore.getState().probing).toBe(true);
    expect(screen.getByText("正在检测 Creator 服务…")).toBeInTheDocument();

    await act(async () => {
      finish(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    });
    await waitFor(() =>
      expect(useCreatorBackendHealthStore.getState().phase).toBe("ready"),
    );
    expect(useCreatorBackendHealthStore.getState().probing).toBe(false);
  });

  it("stays closed while the backend is healthy", () => {
    useCreatorBackendHealthStore.setState({
      phase: "ready",
      checkedAt: "2026-11-17T00:00:00.000Z",
    });

    render(<CreatorBackendBlockingOverlay />);

    expect(document.querySelector("[data-creator-backend-blocked]")).toBeNull();
  });

  it("blocks writes while unavailable and lets the user browse until the next failed probe", () => {
    useCreatorBackendHealthStore.setState({
      phase: "unavailable",
      error: "Creator 服务未就绪或已断开，请稍后重试",
      checkedAt: "2026-11-17T00:00:00.000Z",
    });

    render(<CreatorBackendBlockingOverlay />);

    expect(
      document.querySelector("[data-creator-backend-blocked]"),
    ).not.toBeNull();
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "服务未就绪，暂时无法提交修改",
    );

    fireEvent.click(
      document.querySelector("[data-backend-browse-only]") as HTMLButtonElement,
    );
    expect(document.querySelector("[data-creator-backend-blocked]")).toBeNull();

    // The next failed probe carries a new checkedAt, so the prompt returns.
    act(() => {
      useCreatorBackendHealthStore.setState({
        checkedAt: "2026-11-17T00:00:10.000Z",
      });
    });
    expect(
      document.querySelector("[data-creator-backend-blocked]"),
    ).not.toBeNull();
  });
});
