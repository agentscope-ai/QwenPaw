import { useCallback, useEffect, useState } from "react";
import { tasksApi, type TaskArtifact } from "../../../api/modules/tasks";

export interface UseArtifactFilesOptions {
  sessionId: string | null;
  userId: string;
  graphId?: string | null;
  enabled?: boolean;
}

function truncatePath(path: string, maxLen = 52): string {
  if (path.length <= maxLen) return path;
  const head = Math.max(12, Math.floor(maxLen * 0.38));
  const tail = Math.max(16, Math.floor(maxLen * 0.42));
  return `${path.slice(0, head)}...${path.slice(-tail)}`;
}

export function useArtifactFiles({
  sessionId,
  userId,
  graphId,
  enabled = true,
}: UseArtifactFilesOptions) {
  const [files, setFiles] = useState<TaskArtifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setFiles([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await tasksApi.listFiles(sessionId, userId, {
        ...(graphId ? { graph_id: graphId } : {}),
      });
      setFiles(res.files ?? []);
    } catch (e) {
      setFiles([]);
      setError(e instanceof Error ? e.message : "Failed to load files");
    } finally {
      setLoading(false);
    }
  }, [sessionId, userId, graphId]);

  useEffect(() => {
    if (enabled && sessionId) {
      void refresh();
    } else {
      setFiles([]);
    }
  }, [enabled, sessionId, refresh]);

  return {
    files,
    loading,
    error,
    refresh,
    formatPath: truncatePath,
  };
}
