import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Input } from "@agentscope-ai/design";
import { PlusOutlined, SearchOutlined, SyncOutlined } from "@ant-design/icons";
import { useProviders } from "./useProviders";
import {
  LoadingState,
  ProviderCard,
  CustomProviderModal,
  ModelsSection,
  ProviderConfigModal,
  ModelManageModal,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "../../../api/types/provider";
import { getIsConfigured } from "./utils";
import styles from "./index.module.less";

/* ------------------------------------------------------------------ */
/* Main Page                                                           */
/* ------------------------------------------------------------------ */

function ModelsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { providers, activeModels, loading, error, fetchAll } = useProviders();
  const [addProviderOpen, setAddProviderOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Shared Modal state — only one instance each instead of N per card
  const [configModalProvider, setConfigModalProvider] =
    useState<ProviderInfo | null>(null);
  const [modelsModalProvider, setModelsModalProvider] =
    useState<ProviderInfo | null>(null);

  // Auto-open provider config modal from URL param
  useEffect(() => {
    const providerParam = searchParams.get("provider");
    if (providerParam && providers.length > 0) {
      const target = providers.find((p) => p.id === providerParam);
      if (target) {
        setConfigModalProvider(target);
        setSearchParams({}, { replace: true });
      }
    }
  }, [providers, searchParams, setSearchParams]);

  const refreshProvidersSilently = useCallback(() => {
    void fetchAll(false);
  }, [fetchAll]);

  // Keep modal provider states in sync with the latest providers data
  useEffect(() => {
    if (modelsModalProvider) {
      const fresh = providers.find((p) => p.id === modelsModalProvider.id);
      if (fresh && fresh !== modelsModalProvider) {
        setModelsModalProvider(fresh);
      }
    }
  }, [providers, modelsModalProvider]);

  useEffect(() => {
    if (configModalProvider) {
      const fresh = providers.find((p) => p.id === configModalProvider.id);
      if (fresh && fresh !== configModalProvider) {
        setConfigModalProvider(fresh);
      }
    }
  }, [providers, configModalProvider]);

  const handleOpenConfig = useCallback((provider: ProviderInfo) => {
    setConfigModalProvider(provider);
  }, []);

  const handleOpenModels = useCallback((provider: ProviderInfo) => {
    setModelsModalProvider(provider);
  }, []);

  // P1: Defer search filtering to avoid blocking input responsiveness
  const deferredSearchQuery = useDeferredValue(searchQuery);

  const { freeProviders, paidProviders, localProviders } = useMemo(() => {
    const regular: ProviderInfo[] = [];
    const local: ProviderInfo[] = [];
    for (const p of providers) {
      if (p.is_local) local.push(p);
      else regular.push(p);
    }

    // Sort providers: custom/available first, then configured, then the rest.
    const sortPriority = (provider: ProviderInfo): number => {
      const isConfigured = getIsConfigured(provider);
      const hasModels =
        provider.models.length + provider.extra_models.length > 0;
      const isAvailable = isConfigured && hasModels;

      if (isAvailable && provider.is_custom) return 0;
      if (isAvailable) return 1;
      if (provider.is_custom) return 2;
      if (isConfigured) return 3;
      return 4;
    };

    regular.sort((a, b) => sortPriority(a) - sortPriority(b));

    // Split into free and paid
    const free: ProviderInfo[] = [];
    const paid: ProviderInfo[] = [];
    for (const p of regular) {
      if (p.is_free_tier) free.push(p);
      else paid.push(p);
    }

    // Fuzzy search filter: match provider name (case-insensitive)
    const query = deferredSearchQuery.trim().toLowerCase();
    if (!query) {
      return {
        freeProviders: free,
        paidProviders: paid,
        localProviders: local,
      };
    }
    return {
      freeProviders: free.filter((p) => p.name.toLowerCase().includes(query)),
      paidProviders: paid.filter((p) => p.name.toLowerCase().includes(query)),
      localProviders: local.filter((p) => p.name.toLowerCase().includes(query)),
    };
  }, [providers, deferredSearchQuery]);

  const renderProviderCards = (list: ProviderInfo[]) =>
    list.map((provider) => (
      <ProviderCard
        key={provider.id}
        provider={provider}
        activeModels={activeModels}
        onSaved={refreshProvidersSilently}
        onOpenConfig={handleOpenConfig}
        onOpenModels={handleOpenModels}
      />
    ));

  return (
    <div className={styles.settingsPage}>
      {loading ? (
        <LoadingState message={t("models.loading")} />
      ) : error ? (
        <LoadingState message={error} error onRetry={fetchAll} />
      ) : (
        <>
          {/* ---- LLM Section (top) ---- */}
          <PageHeader
            parent={t("nav.settings")}
            current={t("models.llmTitle")}
          />
          {/* ---- Scrollable Content ---- */}
          <div className={styles.content}>
            <ModelsSection
              providers={providers}
              activeModels={activeModels}
              onSaved={fetchAll}
            />
            {/* ---- Providers Section ---- */}
            <div className={styles.providersBlock}>
              <div className={styles.sectionHeaderRow}>
                <PageHeader
                  current={t("models.providersTitle")}
                  className={styles.providersPageHeader}
                />
                <div className={styles.headerRight}>
                  {/* ---- Search ---- */}
                  <div className={styles.searchRow}>
                    <Input
                      placeholder={t("models.searchPlaceholder")}
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className={styles.searchInput}
                      prefix={<SearchOutlined />}
                      allowClear
                      autoComplete="off"
                      data-form-type="other"
                    />
                    <Button
                      icon={<SyncOutlined />}
                      onClick={() => fetchAll()}
                      className={styles.searchBtn}
                      title={t("common.refresh")}
                    />
                  </div>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => setAddProviderOpen(true)}
                    className={styles.addProviderBtn}
                  >
                    {t("models.addProvider")}
                  </Button>
                </div>
              </div>

              {localProviders.length > 0 && (
                <div className={styles.providerGroup}>
                  <div className={styles.providerCards}>
                    {renderProviderCards(localProviders)}
                  </div>
                </div>
              )}

              {freeProviders.length > 0 && (
                <div className={styles.providerGroup}>
                  <h4 className={styles.providerGroupTitle}>
                    {t("models.freeTierGroup")}
                  </h4>
                  <div className={styles.providerCards}>
                    {renderProviderCards(freeProviders)}
                  </div>
                </div>
              )}

              {paidProviders.length > 0 && (
                <div className={styles.providerGroup}>
                  <h4 className={styles.providerGroupTitle}>
                    {t("models.paidGroup")}
                  </h4>
                  <div className={styles.providerCards}>
                    {renderProviderCards(paidProviders)}
                  </div>
                </div>
              )}
            </div>

            <CustomProviderModal
              open={addProviderOpen}
              onClose={() => setAddProviderOpen(false)}
              onSaved={fetchAll}
            />

            {/* Shared Modal instances — one each for the entire page */}
            {configModalProvider && (
              <ProviderConfigModal
                provider={configModalProvider}
                activeModels={activeModels}
                open={!!configModalProvider}
                onClose={() => setConfigModalProvider(null)}
                onSaved={refreshProvidersSilently}
              />
            )}
            {modelsModalProvider && (
              <ModelManageModal
                provider={modelsModalProvider}
                open={!!modelsModalProvider}
                onClose={() => setModelsModalProvider(null)}
                onSaved={refreshProvidersSilently}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default ModelsPage;
