import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type { EnvVar } from "../../../api/types";

export function useEnvVars() {
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listEnvs();
      if (data) setEnvVars(data);
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : "Failed to load environment variables";
      console.error("Failed to load env vars:", err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return { envVars, loading, error, fetchAll };
}
