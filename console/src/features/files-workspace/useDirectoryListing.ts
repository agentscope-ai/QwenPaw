import { useCallback, useEffect, useRef, useState } from "react";
import { workspaceApi } from "../../api/modules/workspace";
import type { DirectoryPage, WorkspaceRoot } from "./types";

interface Listing extends DirectoryPage {
  identity: string;
  pages: number;
}

export function useDirectoryListing(
  path: string,
  root: WorkspaceRoot,
  chatId: string | undefined,
  projectDirOverride: string | undefined,
  scopeKey: string,
  revision: number,
  enabled = true,
) {
  const identity = JSON.stringify([
    scopeKey,
    chatId,
    projectDirOverride,
    root,
    path,
  ]);
  const requestKey = JSON.stringify([identity, revision]);
  const currentKey = useRef(requestKey);
  currentKey.current = requestKey;
  const sequence = useRef(0);
  const activeRequest = useRef<string>();
  const loadedKey = useRef<string>();
  const snapshot = useRef<Listing>();
  const [listing, setListing] = useState<Listing>();
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(
    async (append = false) => {
      const previous =
        snapshot.current?.identity === identity ? snapshot.current : undefined;
      if (
        append &&
        (!previous?.next_cursor ||
          loadedKey.current !== requestKey ||
          activeRequest.current === requestKey)
      )
        return;
      const id = ++sequence.current;
      const isCurrent = () =>
        sequence.current === id && currentKey.current === requestKey;
      setLoading(true);
      activeRequest.current = requestKey;
      setFailed(false);
      try {
        let cursor = append ? previous?.next_cursor ?? undefined : undefined;
        const entries = append ? [...previous!.entries] : [];
        const targetPages = append ? 1 : previous?.pages ?? 1;
        for (let index = 0; index < targetPages; index++) {
          const page = await workspaceApi.listDirectory(
            path,
            cursor,
            200,
            chatId,
            root,
            projectDirOverride,
          );
          if (!isCurrent()) return;
          entries.push(...page.entries);
          const next = {
            ...page,
            entries,
            identity,
            pages: append ? previous!.pages + 1 : index + 1,
          };
          if (!page.has_more || index + 1 === targetPages) {
            snapshot.current = next;
            loadedKey.current = requestKey;
            setListing(next);
            break;
          }
          cursor = page.next_cursor ?? undefined;
        }
      } catch {
        if (isCurrent()) setFailed(true);
      } finally {
        if (isCurrent()) {
          activeRequest.current = undefined;
          setLoading(false);
        }
      }
    },
    [chatId, identity, path, projectDirOverride, requestKey, root],
  );

  useEffect(() => {
    if (!enabled) {
      sequence.current++;
      activeRequest.current = undefined;
      setLoading(false);
    } else if (loadedKey.current !== requestKey) {
      void load();
    }
  }, [enabled, load, requestKey]);

  useEffect(
    () => () => {
      sequence.current++;
    },
    [],
  );

  const visible = listing?.identity === identity ? listing : undefined;
  return {
    entries: visible?.entries ?? [],
    hasMore: visible?.has_more ?? false,
    loading,
    failed,
    reload: () => load(),
    loadMore: () => load(true),
  };
}
