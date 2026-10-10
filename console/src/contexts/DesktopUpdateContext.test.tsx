import { act, render, renderHook } from "@testing-library/react";
import { type ReactNode } from "react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

// The module under test imports "../tauri/desktopUpdate" and
// "../tauri/backendRuntime"; mocking the same specifiers from this directory
// resolves to those very modules.
const mocks = vi.hoisted(() => ({
  checkDesktopUpdate: vi.fn(),
  checkCachedUpdate: vi.fn(),
  downloadDesktopUpdate: vi.fn(),
  installDesktopUpdate: vi.fn(),
  installDownloadedUpdate: vi.fn(),
  onUpdateEvent: vi.fn(),
  isDesktopApp: vi.fn(),
}));

vi.mock("../tauri/desktopUpdate", () => ({
  checkDesktopUpdate: mocks.checkDesktopUpdate,
  checkCachedUpdate: mocks.checkCachedUpdate,
  downloadDesktopUpdate: mocks.downloadDesktopUpdate,
  installDesktopUpdate: mocks.installDesktopUpdate,
  installDownloadedUpdate: mocks.installDownloadedUpdate,
  onUpdateEvent: mocks.onUpdateEvent,
}));

vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: mocks.isDesktopApp,
}));

import {
  DesktopUpdateProvider,
  useDesktopUpdate,
} from "./DesktopUpdateContext";
import type {
  UpdateError,
  UpdateEventHandlers,
  UpdateProgress,
} from "../tauri/desktopUpdate";

const wrapper = ({ children }: { children: ReactNode }) => (
  <DesktopUpdateProvider>{children}</DesktopUpdateProvider>
);

const renderUpdate = () => renderHook(() => useDesktopUpdate(), { wrapper });

/** Let every queued microtask from the mount effect settle. */
const flush = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};

const err = (over: Partial<UpdateError> = {}): UpdateError => ({
  stage: "download",
  kind: "network",
  message: "socket closed",
  ...over,
});

let unlisten: Mock<() => void>;
/** Handlers captured from the most recent onUpdateEvent subscription. */
let handlers: UpdateEventHandlers;

describe("DesktopUpdateContext", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((m) => m.mockReset());
    mocks.isDesktopApp.mockReturnValue(true);
    mocks.checkCachedUpdate.mockResolvedValue(null);
    mocks.checkDesktopUpdate.mockResolvedValue(null);
    mocks.downloadDesktopUpdate.mockResolvedValue(undefined);
    mocks.installDesktopUpdate.mockResolvedValue(undefined);
    mocks.installDownloadedUpdate.mockResolvedValue(undefined);
    unlisten = vi.fn();
    handlers = {};
    mocks.onUpdateEvent.mockImplementation((h: UpdateEventHandlers) => {
      handlers = h;
      return Promise.resolve(unlisten);
    });
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // ── hook contract ───────────────────────────────────────────────────────

  it("throws when used outside the provider", () => {
    // No wrapper: the context default is null and the hook must refuse rather
    // than hand back a half-initialised value.
    expect(() => renderHook(() => useDesktopUpdate())).toThrow(
      "useDesktopUpdate must be used inside <DesktopUpdateProvider>",
    );
  });

  it("starts in the idle phase with no update information", async () => {
    const { result } = renderUpdate();

    await flush();

    expect(result.current.phase).toBe("idle");
    expect(result.current.hasUpdate).toBe(false);
    expect(result.current.isBackground).toBe(false);
    expect(result.current.supportsLaterInstall).toBe(false);
    expect(result.current.version).toBe("");
    expect(result.current.body).toBe("");
    expect(result.current.downloaded).toBe(0);
    expect(result.current.total).toBeNull();
    expect(result.current.throughputBps).toBe(0);
    expect(result.current.error).toBeNull();
  });

  // ── mount probe: non-desktop ────────────────────────────────────────────

  it("skips both probes and the event subscription outside the desktop app", async () => {
    mocks.isDesktopApp.mockReturnValue(false);
    const { result } = renderUpdate();

    await flush();

    expect(mocks.checkCachedUpdate).not.toHaveBeenCalled();
    expect(mocks.checkDesktopUpdate).not.toHaveBeenCalled();
    expect(mocks.onUpdateEvent).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("idle");
  });

  // ── mount probe: cached update on disk ──────────────────────────────────

  it("resumes a cached download as an already-downloaded background update", async () => {
    mocks.checkCachedUpdate.mockResolvedValue("2.3.0");
    const { result } = renderUpdate();

    await flush();

    expect(result.current.version).toBe("2.3.0");
    expect(result.current.hasUpdate).toBe(true);
    // A cached bundle can always be installed later, regardless of what the
    // remote advertises.
    expect(result.current.supportsLaterInstall).toBe(true);
    expect(result.current.phase).toBe("downloaded");
    expect(result.current.isBackground).toBe(true);
  });

  it("keeps the cached version when the remote advertises a different one", async () => {
    mocks.checkCachedUpdate.mockResolvedValue("2.3.0");
    mocks.checkDesktopUpdate.mockResolvedValue({
      version: "9.9.9",
      body: "notes",
      supportsLaterInstall: false,
    });
    const { result } = renderUpdate();

    await flush();

    // setVersion((prev) => prev || info.version): an already-cached version
    // must win over the remote one.
    expect(result.current.version).toBe("2.3.0");
    expect(result.current.body).toBe("notes");
  });

  it("ignores a null cached version", async () => {
    mocks.checkCachedUpdate.mockResolvedValue(null);
    const { result } = renderUpdate();

    await flush();

    expect(result.current.phase).toBe("idle");
    expect(result.current.hasUpdate).toBe(false);
  });

  it("swallows a cached-update probe failure without failing the mount", async () => {
    mocks.checkCachedUpdate.mockRejectedValue(new Error("disk gone"));
    const { result } = renderUpdate();

    await flush();

    expect(result.current.phase).toBe("idle");
    expect(result.current.error).toBeNull();
    // The remote probe still ran.
    expect(mocks.checkDesktopUpdate).toHaveBeenCalledTimes(1);
  });

  // ── mount probe: remote update ──────────────────────────────────────────

  it("adopts the remote version and trimmed release notes", async () => {
    mocks.checkDesktopUpdate.mockResolvedValue({
      version: "2.4.0",
      body: "  fixed things  ",
      supportsLaterInstall: true,
    });
    const { result } = renderUpdate();

    await flush();

    expect(result.current.version).toBe("2.4.0");
    expect(result.current.body).toBe("fixed things");
    expect(result.current.hasUpdate).toBe(true);
    expect(result.current.supportsLaterInstall).toBe(true);
    // A remote-only update has not been downloaded yet.
    expect(result.current.phase).toBe("idle");
  });

  it("treats a missing body as empty and coerces supportsLaterInstall to a boolean", async () => {
    mocks.checkDesktopUpdate.mockResolvedValue({ version: "2.4.0" });
    const { result } = renderUpdate();

    await flush();

    expect(result.current.body).toBe("");
    expect(result.current.supportsLaterInstall).toBe(false);
  });

  it("ignores a null remote result", async () => {
    mocks.checkDesktopUpdate.mockResolvedValue(null);
    const { result } = renderUpdate();

    await flush();

    expect(result.current.hasUpdate).toBe(false);
    expect(result.current.version).toBe("");
  });

  it("warns but keeps working when the remote probe rejects", async () => {
    const failure = new Error("offline");
    mocks.checkDesktopUpdate.mockRejectedValue(failure);
    const { result } = renderUpdate();

    await flush();

    expect(console.warn).toHaveBeenCalledWith(
      "[updates] desktop update check failed",
      failure,
    );
    expect(result.current.hasUpdate).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("drops probe results that land after unmount", async () => {
    let releaseCached!: (v: string | null) => void;
    mocks.checkCachedUpdate.mockReturnValue(
      new Promise<string | null>((resolve) => {
        releaseCached = resolve;
      }),
    );
    const { unmount } = renderUpdate();

    unmount();
    await act(async () => {
      releaseCached("2.3.0");
      await Promise.resolve();
    });

    // No state update may be attempted on an unmounted provider; reaching here
    // without an act warning is the assertion.
    expect(mocks.checkCachedUpdate).toHaveBeenCalledTimes(1);
  });

  // ── event subscription ──────────────────────────────────────────────────

  it("subscribes to rust-side update events on mount", async () => {
    renderUpdate();

    await flush();

    expect(mocks.onUpdateEvent).toHaveBeenCalledTimes(1);
    const registered = mocks.onUpdateEvent.mock
      .calls[0][0] as UpdateEventHandlers;
    expect(typeof registered.onCheckStart).toBe("function");
    expect(typeof registered.onDownloadProgress).toBe("function");
    expect(typeof registered.onInstallStart).toBe("function");
    expect(typeof registered.onDownloadDone).toBe("function");
    expect(typeof registered.onError).toBe("function");
  });

  it("unsubscribes on unmount", async () => {
    const { unmount } = renderUpdate();

    await flush();
    expect(unlisten).not.toHaveBeenCalled();

    unmount();
    expect(unlisten).toHaveBeenCalledTimes(1);
  });

  it("unsubscribes immediately when the subscription resolves after unmount", async () => {
    let releaseSubscribe!: (u: () => void) => void;
    mocks.onUpdateEvent.mockReturnValue(
      new Promise<() => void>((resolve) => {
        releaseSubscribe = resolve;
      }),
    );
    const { unmount } = renderUpdate();

    unmount();
    await act(async () => {
      releaseSubscribe(unlisten);
      await Promise.resolve();
    });

    // The cancelled branch must tear the listener down rather than leak it.
    expect(unlisten).toHaveBeenCalledTimes(1);
  });

  it("moves to the checking phase when the backend reports a check start", async () => {
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onCheckStart?.();
    });

    expect(result.current.phase).toBe("checking");
  });

  it("moves to the installing phase when the backend reports an install start", async () => {
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onInstallStart?.();
    });

    expect(result.current.phase).toBe("installing");
  });

  it("records the downloaded version when the backend reports completion", async () => {
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onDownloadDone?.({ version: "2.5.0" });
    });

    expect(result.current.phase).toBe("downloaded");
    expect(result.current.version).toBe("2.5.0");
  });

  it("surfaces a backend error as a failed phase", async () => {
    const failure = err({
      stage: "install",
      kind: "signature",
      message: "bad sig",
    });
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onError?.(failure);
    });

    expect(result.current.phase).toBe("failed");
    expect(result.current.error).toEqual(failure);
  });

  // ── download progress and throughput ────────────────────────────────────

  it("reports zero throughput for the very first progress sample", async () => {
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 1000, total: 5000 });
    });

    expect(result.current.phase).toBe("downloading");
    expect(result.current.downloaded).toBe(1000);
    expect(result.current.total).toBe(5000);
    // A single sample has no elapsed time, so no rate can be derived.
    expect(result.current.throughputBps).toBe(0);
  });

  it("derives throughput from the oldest sample inside the window", async () => {
    vi.useFakeTimers();
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 0, total: 10_000 });
    });

    // 1 second and 4 MB later: 4_000_000 bytes / 1 s.
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 4_000_000, total: 10_000 });
    });

    expect(result.current.throughputBps).toBe(4_000_000);
    expect(result.current.downloaded).toBe(4_000_000);
  });

  it("drops samples older than the five second window", async () => {
    vi.useFakeTimers();
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 0, total: null });
    });

    // Beyond the 5 s window the old sample is filtered out, so the newest one
    // becomes the oldest and no rate can be derived again.
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 9_000_000, total: null });
    });

    expect(result.current.throughputBps).toBe(0);
    expect(result.current.downloaded).toBe(9_000_000);
    expect(result.current.total).toBeNull();
  });

  it("clamps a non-increasing byte count to zero throughput", async () => {
    vi.useFakeTimers();
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 5000, total: null });
    });

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    // A restart can report fewer bytes than the previous sample.
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 100, total: null });
    });

    expect(result.current.throughputBps).toBe(0);
    expect(result.current.downloaded).toBe(100);
  });

  // ── startInstall / retry ────────────────────────────────────────────────

  it("takes over the UI when starting an immediate install", async () => {
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.startInstall();
    });

    expect(mocks.installDesktopUpdate).toHaveBeenCalledTimes(1);
    expect(result.current.isBackground).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("exposes retry as the same takeover path", async () => {
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.retry();
    });

    expect(mocks.installDesktopUpdate).toHaveBeenCalledTimes(1);
    expect(mocks.downloadDesktopUpdate).not.toHaveBeenCalled();
  });

  it("resets progress bookkeeping when a new attempt starts", async () => {
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onDownloadProgress?.({ downloaded: 4096, total: 8192 });
      handlers.onError?.(err());
    });
    expect(result.current.downloaded).toBe(4096);
    expect(result.current.phase).toBe("failed");

    await act(async () => {
      await result.current.startInstall();
    });

    expect(result.current.downloaded).toBe(0);
    expect(result.current.total).toBeNull();
    expect(result.current.throughputBps).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("reports a check-stage failure when the immediate install rejects with an Error", async () => {
    mocks.installDesktopUpdate.mockRejectedValueOnce(
      new Error("no space left"),
    );
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.startInstall();
    });

    expect(result.current.phase).toBe("failed");
    expect(result.current.error).toEqual({
      stage: "check",
      kind: "other",
      message: "no space left",
    });
  });

  it("reports a string rejection verbatim", async () => {
    mocks.installDesktopUpdate.mockRejectedValueOnce("rust panic");
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.startInstall();
    });

    expect(result.current.error?.message).toBe("rust panic");
  });

  it("serialises an object rejection rather than rendering [object Object]", async () => {
    mocks.installDesktopUpdate.mockRejectedValueOnce({
      code: 42,
      why: "denied",
    });
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.startInstall();
    });

    expect(result.current.error?.message).toBe(
      JSON.stringify({ code: 42, why: "denied" }),
    );
  });

  // ── startBackgroundDownload ─────────────────────────────────────────────

  it("downloads in the background without taking over the UI", async () => {
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.startBackgroundDownload();
    });

    expect(mocks.downloadDesktopUpdate).toHaveBeenCalledTimes(1);
    expect(mocks.installDesktopUpdate).not.toHaveBeenCalled();
    expect(result.current.isBackground).toBe(true);
  });

  it("reports a check-stage failure when the background download rejects", async () => {
    mocks.downloadDesktopUpdate.mockRejectedValueOnce(
      new Error("tls handshake"),
    );
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.startBackgroundDownload();
    });

    expect(result.current.phase).toBe("failed");
    expect(result.current.isBackground).toBe(true);
    expect(result.current.error).toEqual({
      stage: "check",
      kind: "other",
      message: "tls handshake",
    });
  });

  // ── installDownloaded ───────────────────────────────────────────────────

  it("installs a previously downloaded bundle in the foreground", async () => {
    mocks.checkCachedUpdate.mockResolvedValue("2.3.0");
    const { result } = renderUpdate();

    await flush();
    expect(result.current.isBackground).toBe(true);

    await act(async () => {
      await result.current.installDownloaded();
    });

    expect(mocks.installDownloadedUpdate).toHaveBeenCalledTimes(1);
    expect(result.current.isBackground).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("reports an install-stage failure when installing a downloaded bundle fails", async () => {
    mocks.installDownloadedUpdate.mockRejectedValueOnce(new Error("app moved"));
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.installDownloaded();
    });

    expect(result.current.phase).toBe("failed");
    // Distinct from the takeover paths: the failure happened during install.
    expect(result.current.error).toEqual({
      stage: "install",
      kind: "other",
      message: "app moved",
    });
    expect(result.current.isBackground).toBe(false);
  });

  it("clears a stale error before retrying an install of a downloaded bundle", async () => {
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onError?.(err({ message: "earlier problem" }));
    });
    expect(result.current.error?.message).toBe("earlier problem");

    await act(async () => {
      await result.current.installDownloaded();
    });

    expect(result.current.error).toBeNull();
    expect(result.current.phase).not.toBe("failed");
  });

  // ── dismissFailure ──────────────────────────────────────────────────────

  it("returns to idle and clears the error when a failure is dismissed", async () => {
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onError?.(err());
    });
    expect(result.current.phase).toBe("failed");

    act(() => {
      result.current.dismissFailure();
    });

    expect(result.current.phase).toBe("idle");
    expect(result.current.error).toBeNull();
    expect(result.current.isBackground).toBe(false);
  });

  it("also clears the background flag of a dismissed background failure", async () => {
    const { result } = renderUpdate();

    await flush();
    await act(async () => {
      await result.current.startBackgroundDownload();
    });
    act(() => {
      handlers.onError?.(err());
    });
    expect(result.current.isBackground).toBe(true);

    act(() => {
      result.current.dismissFailure();
    });

    expect(result.current.isBackground).toBe(false);
  });

  // ── context identity ────────────────────────────────────────────────────

  it("keeps the action identities stable across unrelated renders", async () => {
    const { result, rerender } = renderUpdate();

    await flush();
    const first = {
      startInstall: result.current.startInstall,
      startBackgroundDownload: result.current.startBackgroundDownload,
      installDownloaded: result.current.installDownloaded,
      dismissFailure: result.current.dismissFailure,
    };

    rerender();

    expect(result.current.startInstall).toBe(first.startInstall);
    expect(result.current.startBackgroundDownload).toBe(
      first.startBackgroundDownload,
    );
    expect(result.current.installDownloaded).toBe(first.installDownloaded);
    expect(result.current.dismissFailure).toBe(first.dismissFailure);
  });

  it("renders the subtree it wraps", async () => {
    // The provider must pass children through instead of swallowing them.
    const { getByTestId } = render(
      <DesktopUpdateProvider>
        <span data-testid="child marker">hello</span>
      </DesktopUpdateProvider>,
    );

    await flush();

    expect(getByTestId("child marker")).toHaveTextContent("hello");
  });

  // ── progress payload passthrough ────────────────────────────────────────

  it("accepts a progress payload with an unknown total", async () => {
    const payload: UpdateProgress = {
      downloaded: 10,
      total: undefined as unknown as null,
    };
    const { result } = renderUpdate();

    await flush();
    act(() => {
      handlers.onDownloadProgress?.(payload);
    });

    expect(result.current.total).toBeNull();
  });
});
