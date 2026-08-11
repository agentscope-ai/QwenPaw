import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import type { BrowseDirsResponse } from "../../api/modules/projectDirectory";

interface UseDirectoryBrowserOptions {
  /** Where to start. Defaults to the user's home directory. */
  initialPath?: string;
  /** Skip fetching entirely (e.g. the browser UI is collapsed). */
  enabled?: boolean;
  /** Called after each successful listing, e.g. to reset scroll position. */
  onLoaded?: () => void;
}

export interface DirectoryBrowserState {
  /** The path we last asked for; may differ from `data.current` while loading. */
  path: string;
  data: BrowseDirsResponse | null;
  loading: boolean;
  error: string | null;
  showHidden: boolean;
  /** The raw state setter, so callers can toggle with `(v) => !v`. */
  setShowHidden: Dispatch<SetStateAction<boolean>>;
  navigate: (path: string) => void;
  /** Path segments of the current directory, for a breadcrumb. */
  breadcrumb: string[];
}

/**
 * Server-side directory browsing state.
 *
 * Extracted so the coding-project modal and the chat project-dir popover
 * share one implementation of the fiddly part: a sequence guard that drops
 * out-of-order responses. Without it, clicking quickly through folders can
 * land you on an earlier directory's listing, because a slow response for
 * the folder you already left arrives last and wins.
 */
export function useDirectoryBrowser(
  options: UseDirectoryBrowserOptions = {},
): DirectoryBrowserState {
  const { initialPath = "~", enabled = true, onLoaded } = options;

  const [path, setPath] = useState(initialPath);
  const [data, setData] = useState<BrowseDirsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);

  const navSeq = useRef(0);
  // Read through refs so `navigate` stays referentially stable and does not
  // retrigger the effects that call it.
  const showHiddenRef = useRef(showHidden);
  showHiddenRef.current = showHidden;
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;
  const pathRef = useRef(path);
  pathRef.current = path;

  const navigate = useCallback((next: string) => {
    const seq = ++navSeq.current;
    setPath(next);
    setLoading(true);
    setError(null);
    projectDirectoryApi
      .browseDirs(next, showHiddenRef.current)
      .then((res) => {
        if (seq !== navSeq.current) return;
        setData(res);
        onLoadedRef.current?.();
      })
      .catch((err: unknown) => {
        if (seq !== navSeq.current) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (seq === navSeq.current) setLoading(false);
      });
  }, []);

  // Initial listing, and re-listing when the hidden-folder toggle flips.
  // navSeq already discards stale responses, so re-fetching unconditionally
  // is safe. `path` is intentionally not a dependency: navigate() sets it,
  // and including it would loop.
  useEffect(() => {
    if (!enabled) return;
    navigate(pathRef.current);
  }, [enabled, showHidden, navigate]);

  const breadcrumb = (data?.current ?? "").split(/[\\/]/).filter(Boolean);

  return {
    path,
    data,
    loading,
    error,
    showHidden,
    setShowHidden,
    navigate,
    breadcrumb,
  };
}
