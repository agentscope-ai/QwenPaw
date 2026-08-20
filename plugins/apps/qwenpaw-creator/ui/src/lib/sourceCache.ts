/** Shared state for URL-backed original footage caching (built-in examples). */

import { useCallback, useEffect, useState } from "react";
import { downloadSourceCache, getSourceCache } from "@/api/creator";
import { startVisiblePolling } from "@/lib/visiblePolling";
import type { SourceCacheVersionView } from "@/contracts/creator";

export interface SourceCacheStatus {
  loading: boolean;
  versions: SourceCacheVersionView[];
  /** True when an enabled project still has uncached original footage. */
  originalsMissing: boolean;
  allCached: boolean;
  anyDownloading: boolean;
  triggering: boolean;
  download: (assetVersionId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

/**
 * Track the local cache state of every remote original-footage version of one
 * Project. `enabled` should only be true for bundled example Projects, whose
 * archives ship the trimmed clips but not the gigabyte-scale originals.
 */
export function useSourceCache(
  projectId: string | null,
  enabled: boolean,
): SourceCacheStatus {
  const [versions, setVersions] = useState<SourceCacheVersionView[]>([]);
  const [loading, setLoading] = useState(false);
  const [triggering, setTriggering] = useState(false);

  const refresh = useCallback(async () => {
    if (!projectId || !enabled) return;
    try {
      const result = await getSourceCache(projectId);
      setVersions(result.versions ?? []);
    } catch {
      // Older backend without the source-cache routes: nothing to gate on.
      setVersions([]);
    }
  }, [projectId, enabled]);

  useEffect(() => {
    if (!projectId || !enabled) {
      setVersions([]);
      return;
    }
    setLoading(true);
    void refresh().finally(() => setLoading(false));
  }, [projectId, enabled, refresh]);

  const anyDownloading = versions.some(
    (version) => version.state === "downloading",
  );

  // Keep progress fresh while the backend streams the original footage in.
  useEffect(() => {
    if (!projectId || !enabled || !anyDownloading) return undefined;
    return startVisiblePolling(() => void refresh(), 2_000);
  }, [projectId, enabled, anyDownloading, refresh]);

  const download = useCallback(
    async (assetVersionId: string) => {
      if (!projectId) return;
      setTriggering(true);
      try {
        await downloadSourceCache(projectId, assetVersionId);
        await refresh();
      } finally {
        setTriggering(false);
      }
    },
    [projectId, refresh],
  );

  return {
    loading,
    versions,
    originalsMissing: enabled && versions.some((version) => !version.cached),
    allCached:
      enabled && versions.length > 0 && versions.every((v) => v.cached),
    anyDownloading,
    triggering,
    download,
    refresh,
  };
}
