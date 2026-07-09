import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  fetchPluginCatalog,
  type OfficialPluginCatalogEntry,
} from "@/api/modules/plugin";

export interface UseCreatorAppsResult {
  apps: OfficialPluginCatalogEntry[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useCreatorApps(): UseCreatorAppsResult {
  const { t } = useTranslation();
  const [apps, setApps] = useState<OfficialPluginCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPluginCatalog();
      const apps = (data.plugins ?? []).filter(
        (entry) => entry.kind.toLowerCase() === "app",
      );
      setApps(apps);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("creator.loadFailed"));
      setApps([]);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { apps, loading, error, refresh };
}
