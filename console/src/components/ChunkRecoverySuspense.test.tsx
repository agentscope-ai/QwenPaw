import { act, cleanup, render, screen } from "@testing-library/react";
import { lazy, StrictMode, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getFrontendBuildId } from "../utils/chunkRecovery";
import { ChunkRecoverySuspense } from "./ChunkRecoverySuspense";

describe("committed page recovery", () => {
  const reloadKey = "qwenpaw:chunk-reload-build";
  let guard: string;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    sessionStorage.clear();
    guard = JSON.stringify({ build: getFrontendBuildId(), attempts: 2 });
    sessionStorage.setItem(reloadKey, guard);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("starts the minute only after a pending lazy page commits", async () => {
    let finish!: (module: { default: () => ReactElement }) => void;
    const Page = lazy(
      () =>
        new Promise<{ default: () => ReactElement }>((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <ChunkRecoverySuspense fallback="loading page">
        <Page />
      </ChunkRecoverySuspense>,
    );
    expect(screen.getByText("loading page")).toBeVisible();
    act(() => vi.advanceTimersByTime(120_000));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);

    await act(async () => {
      finish({ default: () => <div>ready page</div> });
    });
    expect(screen.getByText("ready page")).toBeVisible();
    act(() => vi.advanceTimersByTime(59_999));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    act(() => vi.advanceTimersByTime(1));
    expect(sessionStorage.getItem(reloadKey)).toBeNull();
  });

  it("blocks healthy ancestors and sibling windows while a nested page loads", async () => {
    let finish!: (module: { default: () => ReactElement }) => void;
    const Page = lazy(
      () =>
        new Promise<{ default: () => ReactElement }>((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <ChunkRecoverySuspense fallback="loading desktop">
        <ChunkRecoverySuspense fallback="loading window">
          <Page />
        </ChunkRecoverySuspense>
        <ChunkRecoverySuspense fallback="loading sibling">
          <div>healthy sibling</div>
        </ChunkRecoverySuspense>
      </ChunkRecoverySuspense>,
    );
    expect(screen.getByText("healthy sibling")).toBeVisible();
    expect(screen.getByText("loading window")).toBeVisible();
    act(() => vi.advanceTimersByTime(120_000));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);

    await act(async () => {
      finish({ default: () => <div>ready window</div> });
    });
    expect(screen.getByText("ready window")).toBeVisible();
    act(() => vi.advanceTimersByTime(59_999));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    act(() => vi.advanceTimersByTime(1));
    expect(sessionStorage.getItem(reloadKey)).toBeNull();
  });

  it("interrupts recovery when Suspense hides already committed content", async () => {
    let finish!: () => void;
    let resolved = false;
    const pending = new Promise<void>((resolve) => {
      finish = () => {
        resolved = true;
        resolve();
      };
    });
    function Page({ loading }: { loading: boolean }) {
      if (loading && !resolved) throw pending;
      return <div>ready page</div>;
    }
    const view = (loading: boolean) => (
      <ChunkRecoverySuspense fallback="loading again">
        <Page loading={loading} />
      </ChunkRecoverySuspense>
    );
    const { rerender } = render(view(false));
    act(() => vi.advanceTimersByTime(40_000));
    rerender(view(true));
    expect(screen.getByText("loading again")).toBeVisible();
    expect(screen.getByText("ready page")).not.toBeVisible();
    act(() => vi.advanceTimersByTime(120_000));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);

    await act(async () => finish());
    expect(screen.getByText("ready page")).toBeVisible();
    act(() => vi.advanceTimersByTime(59_999));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    act(() => vi.advanceTimersByTime(1));
    expect(sessionStorage.getItem(reloadKey)).toBeNull();
  });

  it("cleans up the interval through StrictMode mount and unmount", () => {
    const page = (
      <StrictMode>
        <ChunkRecoverySuspense fallback="loading">
          <div>ready page</div>
        </ChunkRecoverySuspense>
      </StrictMode>
    );
    const { unmount } = render(page);
    act(() => vi.advanceTimersByTime(30_000));
    unmount();
    act(() => vi.advanceTimersByTime(60_000));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);

    render(page);
    act(() => vi.advanceTimersByTime(59_999));
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    act(() => vi.advanceTimersByTime(1));
    expect(sessionStorage.getItem(reloadKey)).toBeNull();
  });
});
