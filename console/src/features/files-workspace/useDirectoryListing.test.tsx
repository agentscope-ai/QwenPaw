import { StrictMode, type PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDirectoryListing } from "./useDirectoryListing";
import type { DirectoryPage, WorkspaceRoot } from "./types";

const listDirectory = vi.hoisted(() => vi.fn());
vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: { listDirectory },
}));

function page(name: string, cursor: string | null = null): DirectoryPage {
  return {
    directory: "",
    entries: [
      {
        name,
        path: name,
        kind: "file",
        size: 1,
        modified_at: "2026-10-09T00:00:00Z",
        preview_kind: "text",
      },
    ],
    next_cursor: cursor,
    has_more: cursor !== null,
  };
}

function deferred() {
  let resolve!: (value: DirectoryPage) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<DirectoryPage>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const initialProps = {
  revision: 0,
  root: "project" as WorkspaceRoot,
  enabled: true,
};
function renderListing(
  wrapper?: (props: PropsWithChildren) => React.ReactNode,
) {
  return renderHook(
    ({ revision, root, enabled }) =>
      useDirectoryListing(
        "",
        root,
        undefined,
        undefined,
        "agent:default",
        revision,
        enabled,
      ),
    { initialProps, wrapper },
  );
}

describe("directory listing request lifecycle", () => {
  beforeEach(() => {
    listDirectory.mockReset();
  });

  it.each([true, false])(
    "reports the initial loading state before effects when enabled=%s",
    (enabled) => {
      listDirectory.mockReturnValue(deferred().promise);
      const renders: boolean[] = [];
      renderHook(() => {
        const listing = useDirectoryListing(
          "",
          "project",
          undefined,
          undefined,
          "agent:default",
          0,
          enabled,
        );
        renders.push(listing.loading);
        return listing;
      });
      expect(renders[0]).toBe(enabled);
      expect(listDirectory).toHaveBeenCalledTimes(enabled ? 1 : 0);
    },
  );

  it("ignores a stale first-page response after refreshing", async () => {
    const old = deferred();
    listDirectory
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(page("fresh.txt"));
    const { result, rerender } = renderListing();
    rerender({ ...initialProps, revision: 1 });
    await waitFor(() =>
      expect(result.current.entries[0]?.name).toBe("fresh.txt"),
    );
    await act(async () => old.resolve(page("stale.txt", "stale-cursor")));
    expect(result.current.entries[0].name).toBe("fresh.txt");
    expect(result.current.hasMore).toBe(false);
  });

  it("ignores stale errors and loading completions during a newer refresh", async () => {
    const old = deferred();
    const fresh = deferred();
    listDirectory
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(fresh.promise);
    const { result, rerender } = renderListing();
    rerender({ ...initialProps, revision: 1 });
    await act(async () => old.reject(new Error("Old request failed")));
    expect(result.current.loading).toBe(true);
    expect(result.current.failed).toBe(false);
    await act(async () => fresh.resolve(page("fresh.txt")));
    expect(result.current.loading).toBe(false);
    expect(result.current.entries[0].name).toBe("fresh.txt");
  });

  it("keeps all cached pages when a refreshed later page fails and allows retry", async () => {
    listDirectory
      .mockResolvedValueOnce(page("before.txt", "old-cursor"))
      .mockResolvedValueOnce(page("second.txt"));
    const { result, rerender } = renderListing();
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    await act(async () => result.current.loadMore());
    listDirectory
      .mockResolvedValueOnce(page("after.txt", "new-cursor"))
      .mockRejectedValueOnce(new Error("Page failed"));
    rerender({ ...initialProps, revision: 1 });
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.entries.map((e) => e.name)).toEqual([
      "before.txt",
      "second.txt",
    ]);
    expect(result.current.loading).toBe(false);
    listDirectory
      .mockResolvedValueOnce(page("after.txt", "retry-cursor"))
      .mockResolvedValueOnce(page("new-second.txt"));
    await act(async () => result.current.reload());
    expect(result.current.entries.map((e) => e.name)).toEqual([
      "after.txt",
      "new-second.txt",
    ]);
    expect(result.current.failed).toBe(false);
  });

  it("stops rebuilding pages when a directory shrinks", async () => {
    listDirectory
      .mockResolvedValueOnce(page("first.txt", "page2"))
      .mockResolvedValueOnce(page("second.txt"));
    const { result, rerender } = renderListing();
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    await act(async () => result.current.loadMore());
    listDirectory.mockClear().mockResolvedValue(page("remaining.txt"));
    rerender({ ...initialProps, revision: 1 });
    await waitFor(() => expect(result.current.entries).toHaveLength(1));
    expect(listDirectory).toHaveBeenCalledTimes(1);
    expect(result.current.hasMore).toBe(false);
  });

  it("isolates root identities and ignores responses from the old root", async () => {
    const old = deferred();
    listDirectory
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(page("workspace.txt"));
    const { result, rerender } = renderListing();
    rerender({ ...initialProps, root: "workspace" });
    await waitFor(() =>
      expect(result.current.entries[0]?.name).toBe("workspace.txt"),
    );
    await act(async () => old.resolve(page("old-project.txt")));
    expect(result.current.entries[0].name).toBe("workspace.txt");
  });

  it("does not continue a paginated refresh after unmounting", async () => {
    listDirectory
      .mockResolvedValueOnce(page("first.txt", "page2"))
      .mockResolvedValueOnce(page("second.txt"));
    const { result, rerender, unmount } = renderListing();
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    await act(async () => result.current.loadMore());
    const pending = deferred();
    listDirectory.mockClear().mockReturnValue(pending.promise);
    rerender({ ...initialProps, revision: 1 });
    unmount();
    await act(async () => pending.resolve(page("new-first.txt", "new-page2")));
    expect(listDirectory).toHaveBeenCalledTimes(1);
  });

  it("supports StrictMode effect replay", async () => {
    const old = deferred();
    listDirectory
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(page("fresh.txt"));
    const { result } = renderListing(({ children }) => (
      <StrictMode>{children}</StrictMode>
    ));
    await waitFor(() =>
      expect(result.current.entries[0]?.name).toBe("fresh.txt"),
    );
    await act(async () => old.resolve(page("stale.txt")));
    expect(result.current.entries[0].name).toBe("fresh.txt");
  });
});
