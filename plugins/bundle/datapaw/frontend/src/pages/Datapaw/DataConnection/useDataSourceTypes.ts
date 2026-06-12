import { useCallback, useEffect, useState } from "react";
import { httpDataSourceApi } from "../../../api/modules/dataSource/http";
import type { DataSourceTypeInfo } from "../../../api/types/dataSource";

export function useDataSourceTypes() {
  const [types, setTypes] = useState<DataSourceTypeInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const loadTypes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await httpDataSourceApi.listTypes();
      setTypes(res.items ?? []);
    } catch (error) {
      console.error("Failed to load data source types:", error);
      setTypes([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTypes();
  }, [loadTypes]);

  return { types, loading, reload: loadTypes };
}
