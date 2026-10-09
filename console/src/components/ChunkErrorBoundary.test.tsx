import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../i18n", () => ({
  default: { t: (key: string) => key },
}));

vi.mock("../api/modules/hub", () => ({
  hubApi: { restartOwnRuntime: vi.fn() },
}));

vi.mock("../utils/clipboard", () => ({
  copyText: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../utils/chunkRecovery", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../utils/chunkRecovery")>()),
  reloadAfterChunkError: vi.fn(() => false),
}));

import { hubApi } from "../api/modules/hub";
import { ChunkErrorBoundary } from "./ChunkErrorBoundary";
import { reloadAfterChunkError } from "../utils/chunkRecovery";
import { lazyWithRetry } from "../utils/lazyWithRetry";
import { copyText } from "../utils/clipboard";
import {
  readChunkDiagnostic,
  saveChunkDiagnostic,
  captureChunkDiagnostic,
} from "../utils/chunkDiagnostics";

function BrokenPage(): ReactElement {
  throw new Error("render failed");
}

describe("ChunkErrorBoundary runtime recovery", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(null, {
          status: 200,
          headers: { "content-type": "text/html" },
        }),
      ),
    );
    sessionStorage.clear();
    vi.mocked(reloadAfterChunkError).mockImplementation(() => false);
    vi.mocked(copyText).mockResolvedValue(undefined);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("retries a rejected page when its route is revisited", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const factory = vi
      .fn()
      .mockRejectedValue(
        new TypeError(
          "Failed to fetch dynamically imported module: /assets/page.js",
        ),
      );
    const Page = lazyWithRetry(factory);
    const view = (key: string, showPage = true) => (
      <ChunkErrorBoundary resetKey={key}>
        <Suspense fallback="loading">
          {showPage ? <Page /> : <div>other page</div>}
        </Suspense>
      </ChunkErrorBoundary>
    );
    const { rerender } = render(view("broken"));
    await screen.findByText("chunkError.title", {}, { timeout: 6000 });
    expect(factory).toHaveBeenCalledTimes(4);
    await waitFor(() => expect(reloadAfterChunkError).toHaveBeenCalledOnce());
    expect(readChunkDiagnostic()?.attempts).toBe(4);

    factory.mockResolvedValue({ default: () => <div>recovered page</div> });
    rerender(view("other", false));
    await screen.findByText("other page");
    rerender(view("broken"));
    await screen.findByText("recovered page");
    expect(factory).toHaveBeenCalledTimes(5);
  });

  it("stops retries and offers recovery for a persistently unavailable page", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const factory = vi
      .fn()
      .mockRejectedValue(new TypeError("Importing a module script failed."));
    const Page = lazyWithRetry(factory);
    render(
      <ChunkErrorBoundary>
        <Suspense fallback="loading">
          <Page />
        </Suspense>
      </ChunkErrorBoundary>,
    );
    await screen.findByText("chunkError.title", {}, { timeout: 6000 });
    expect(factory).toHaveBeenCalledTimes(4);
    await waitFor(() => expect(reloadAfterChunkError).toHaveBeenCalledOnce());
    expect(
      screen.getByRole("button", { name: "chunkError.reload" }),
    ).toBeVisible();
  });

  it("displays and copies original errors separately from resource rechecks", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function MissingModule(): ReactElement {
      throw new TypeError(
        `Failed to fetch dynamically imported module: ${location.origin}/assets/page.js`,
      );
    }
    render(
      <ChunkErrorBoundary>
        <MissingModule />
      </ChunkErrorBoundary>,
    );
    await screen.findByText("chunkError.observations.html");
    expect(screen.getByText("chunkError.details")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "chunkError.copy" }));
    await screen.findByRole("button", { name: "chunkError.copied" });
    const copied = JSON.parse(vi.mocked(copyText).mock.calls[0][0]);
    expect(copied.current.originalError.name).toBe("TypeError");
    expect(copied.current.originalResourceStatus).toBeNull();
    expect(copied.current.recheck).toMatchObject({
      status: 200,
      outcome: "html",
    });
  });

  it("preserves a diagnostic before automatic refresh and includes the earlier report", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const error = new TypeError("Importing a module script failed.");
    const previous = captureChunkDiagnostic(error);
    previous.automaticReloadAttempted = true;
    saveChunkDiagnostic(previous);
    vi.mocked(reloadAfterChunkError).mockImplementation((persist) => {
      persist?.();
      expect(readChunkDiagnostic()?.automaticReloadAttempted).toBe(true);
      return true;
    });
    function MissingModule(): ReactElement {
      throw error;
    }
    render(
      <ChunkErrorBoundary>
        <MissingModule />
      </ChunkErrorBoundary>,
    );
    await waitFor(() => expect(reloadAfterChunkError).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: "chunkError.copy" }));
    await waitFor(() => expect(copyText).toHaveBeenCalledOnce());
    expect(
      JSON.parse(vi.mocked(copyText).mock.calls[0][0]).beforeAutomaticReload,
    ).toEqual(previous);
  });

  it("keeps manual recovery when copying fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.mocked(copyText).mockRejectedValue(new Error("clipboard blocked"));
    function MissingModule(): ReactElement {
      throw new TypeError("Importing a module script failed.");
    }
    render(
      <ChunkErrorBoundary>
        <MissingModule />
      </ChunkErrorBoundary>,
    );
    await screen.findByText("chunkError.details");
    fireEvent.click(screen.getByRole("button", { name: "chunkError.copy" }));
    await screen.findByText("chunkError.copyFailed");
    expect(
      screen.getByRole("button", { name: "chunkError.reload" }),
    ).toBeVisible();
  });

  it("does not refresh a healthy route when an earlier recheck finishes late", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    let finish!: (response: Response) => void;
    vi.mocked(fetch).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    function MissingModule(): ReactElement {
      throw new TypeError(
        `Failed to fetch dynamically imported module: ${location.origin}/assets/page.js`,
      );
    }
    const { rerender } = render(
      <ChunkErrorBoundary resetKey="broken">
        <MissingModule />
      </ChunkErrorBoundary>,
    );
    await screen.findByText("chunkError.checking");
    rerender(
      <ChunkErrorBoundary resetKey="healthy">
        <div>healthy page</div>
      </ChunkErrorBoundary>,
    );
    await screen.findByText("healthy page");
    finish(new Response(null, { status: 404 }));
    await waitFor(() => expect(screen.getByText("healthy page")).toBeVisible());
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
  });

  it.each([
    "module initialization failed",
    "crypto.randomUUID is not a function",
    "Failed to fetch",
  ])("does not retry or auto-refresh %s", async (message) => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const factory = vi.fn().mockRejectedValue(new Error(message));
    const Page = lazyWithRetry(factory);
    render(
      <ChunkErrorBoundary>
        <Suspense fallback="loading">
          <Page />
        </Suspense>
      </ChunkErrorBoundary>,
    );
    await screen.findByText("chunkError.genericTitle");
    expect(factory).toHaveBeenCalledOnce();
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
  });

  it("offers Hub users a runtime restart when a page fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.mocked(hubApi.restartOwnRuntime).mockRejectedValueOnce(
      new Error("restart failed"),
    );

    render(
      <ChunkErrorBoundary canRestartRuntime>
        <BrokenPage />
      </ChunkErrorBoundary>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "account.runtimeRestart" }),
    );

    await waitFor(() => {
      expect(hubApi.restartOwnRuntime).toHaveBeenCalledOnce();
      expect(screen.getByText("restart failed")).toBeInTheDocument();
    });
  });

  it("does not expose Hub recovery in standalone mode", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ChunkErrorBoundary>
        <BrokenPage />
      </ChunkErrorBoundary>,
    );

    expect(
      screen.queryByRole("button", { name: "account.runtimeRestart" }),
    ).not.toBeInTheDocument();
    expect(reloadAfterChunkError).not.toHaveBeenCalled();
  });
});
