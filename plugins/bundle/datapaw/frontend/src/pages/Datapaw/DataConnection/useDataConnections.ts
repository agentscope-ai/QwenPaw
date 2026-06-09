import { useCallback, useEffect, useState } from "react";
import { dataSourceApi } from "../../../api/modules/dataSource";
import type { DataSourceRecord } from "../../../api/types/dataSource";

export function useDataConnections() {
  const [connections, setConnections] = useState<DataSourceRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await dataSourceApi.list();
      setConnections(res.items);
    } catch (error) {
      console.error("Failed to load data sources:", error);
      setConnections([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const removeConnection = useCallback(
    async (id: string) => {
      await dataSourceApi.remove(id);
      setConnections((prev) => prev.filter((item) => item.id !== id));
    },
    [],
  );

  return {
    connections,
    loading,
    refresh,
    removeConnection,
  };
}
