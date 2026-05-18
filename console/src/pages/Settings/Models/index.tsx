import { useCallback, useMemo, useState } from "react";
import { Button, Input } from "@agentscope-ai/design";
import { PlusOutlined, SearchOutlined, SyncOutlined } from "@ant-design/icons";
import { useProviders } from "./useProviders";
import {
  LoadingState,
  ProviderCard,
  CustomProviderModal,
  ModelsSection,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "../../../api/types/provider";
import styles from "./index.module.less";

/* ------------------------------------------------------------------ */
/* Main Page                                                           */
/* ------------------------------------------------------------------ */

function ModelsPage() {
  const { t } = useTranslation();
  const { providers, activeModels, routingConfig, loading, error, fetchAll } =
    useProviders();
  const [addProviderOpen, setAddProviderOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const refreshProvidersSilently = useCallback(() => {
    void fetchAll(false);
  }, [fetchAll]);

  const { regularProviders, localProviders } = useMemo(() => {
    const regular: ProviderInfo[] = [];
    const local: ProviderInfo[] = [];
    for (const p of providers) {
      if (p.is_local) local.push(p);
      else regular.push(p);
    }

    // Sort providers: custom/available first, then configured, then the rest.
    // This mirrors the isConfigured logic in RemoteProviderCard.
    const sortPriority = (provider: ProviderInfo): number => {
      let isConfigured = false;
      if (provider.id === "qwenpaw-local") {
        isConfigured = true;
      } else if (provider.is_custom && provider.base_url) {
        isConfigured = true;
      } else if (provider.require_api_key === false) {
        isConfigured = true;
      } else if (provider.require_api_key && provider.api_key) {
        isConfigured = true;
      }

      const hasModels =
        provider.models.length + provider.extra_models.length > 0;
      const isAvailable = isConfigured && hasModels;

      // Lower number = higher priority (shown first)
      // Available providers (configured + has models) always come first,
      // then custom providers, then configured-only, then unconfigured.
      if (isAvailable && provider.is_custom) return 0;
      if (isAvailable) return 1;
      if (provider.is_custom) return 2;
      if (isConfigured) return 3;
      return 4;
    };

    regular.sort((a, b) => sortPriority(a) - sortPriority(b));

    // Fuzzy search filter: match provider name (case-insensitive)
    const query = searchQuery.trim().toLowerCase();
    if (!query) {
      return { regularProviders: regular, localProviders: local };
    }
    return {
      regularProviders: regular.filter((p) =>
        p.name.toLowerCase().includes(query),
      ),
      localProviders: local.filter((p) => p.name.toLowerCase().includes(query)),
    };
  }, [providers, searchQuery]);

  const renderProviderCards = (list: ProviderInfo[]) =>
    list.map((provider) => (
      <ProviderCard
        key={provider.id}
        provider={provider}
        activeModels={activeModels}
        onSaved={refreshProvidersSilently}
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
              routingConfig={routingConfig}
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
                  {/* <h4 className={styles.providerGroupTitle}>
                  {t("models.localEmbedded")}
                </h4> */}
                  <div className={styles.providerCards}>
                    {renderProviderCards(localProviders)}
                  </div>
                </div>
              )}

              {regularProviders.length > 0 && (
                <div className={styles.providerGroup}>
                  <div className={styles.providerCards}>
                    {renderProviderCards(regularProviders)}
                  </div>
                </div>
              )}
            </div>

            <CustomProviderModal
              open={addProviderOpen}
              onClose={() => setAddProviderOpen(false)}
              onSaved={fetchAll}
            />
          </div>
        </>
      )}
    </div>
  );
}

export default ModelsPage;
