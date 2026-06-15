import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Input, Modal } from "@agentscope-ai/design";
import { PlusOutlined, SearchOutlined, SyncOutlined, DownOutlined } from "@ant-design/icons";
import { useProviders } from "./useProviders";
import {
  LoadingState,
  ProviderCard,
  ProviderGroupCard,
  CustomProviderModal,
  ModelsSection,
  ProviderConfigModal,
  ModelManageModal,
} from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "../../../api/types/provider";
import { getIsConfigured, groupProviders } from "./utils";
import { ProviderIcon } from "./components/ProviderIconComponent";
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
  const [variantSelectGroup, setVariantSelectGroup] = useState<{
    key: string;
    name: string;
    providers: ProviderInfo[];
  } | null>(null);
  const [llmCollapsed, setLlmCollapsed] = useState(true);

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

  const {
    localConfigured,
    localAvailable,
    cloudConfiguredGrouped,
    cloudConfiguredUngrouped,
    cloudAvailableGroups,
  } = useMemo(() => {
    const localConf: ProviderInfo[] = [];
    const localAvail: ProviderInfo[] = [];
    const cloudConf: ProviderInfo[] = [];
    const cloudAvail: ProviderInfo[] = [];

    const isReady = (p: ProviderInfo) => {
      const hasModels =
        p.models.length + p.extra_models.length > 0;
      if (p.is_local) return hasModels;
      return getIsConfigured(p);
    };

    // QwenPaw Local is always "configured" (embedded)
    const isEmbedded = (p: ProviderInfo) =>
      p.id === "qwenpaw-local" || p.id === "copaw-local";

    // Separate local vs cloud first
    const allCloud: ProviderInfo[] = [];
    for (const p of providers) {
      if (p.is_local || p.is_custom) {
        if (isEmbedded(p) || isReady(p)) localConf.push(p);
        else localAvail.push(p);
      } else {
        allCloud.push(p);
      }
    }

    // For cloud: if ANY variant in a group is configured,
    // pull the entire group into configured
    const groupConfigured = new Set<string>();
    for (const p of allCloud) {
      if (p.provider_group && isReady(p)) {
        groupConfigured.add(p.provider_group);
      }
    }
    for (const p of allCloud) {
      if (p.provider_group && groupConfigured.has(p.provider_group)) {
        cloudConf.push(p);
      } else if (!p.provider_group && isReady(p)) {
        cloudConf.push(p);
      } else {
        cloudAvail.push(p);
      }
    }

    const sortPriority = (provider: ProviderInfo): number => {
      const hasModels =
        provider.models.length + provider.extra_models.length > 0;
      if (hasModels && provider.is_custom) return 0;
      if (hasModels) return 1;
      return 2;
    };
    localConf.sort((a, b) => sortPriority(a) - sortPriority(b));
    cloudConf.sort((a, b) => sortPriority(a) - sortPriority(b));

    const cloudResult = groupProviders(cloudConf);

    // Group available cloud providers by brand for compact display
    const availGroupMap = new Map<
      string,
      { name: string; providers: ProviderInfo[]; hasFree: boolean }
    >();
    const availUngrouped: ProviderInfo[] = [];
    for (const p of cloudAvail) {
      if (p.provider_group) {
        const existing = availGroupMap.get(p.provider_group);
        if (existing) {
          existing.providers.push(p);
          if (p.is_free_tier) existing.hasFree = true;
        } else {
          availGroupMap.set(p.provider_group, {
            name: p.provider_group_name || p.provider_group,
            providers: [p],
            hasFree: !!p.is_free_tier,
          });
        }
      } else {
        availUngrouped.push(p);
      }
    }
    const cloudAvailGroups = [
      ...Array.from(availGroupMap.entries()).map(
        ([key, val]) => ({
          key,
          name: val.name,
          hasFree: val.hasFree,
          firstProvider: val.providers[0],
          providers: val.providers,
        }),
      ),
      ...availUngrouped.map((p) => ({
        key: p.id,
        name: p.name,
        hasFree: !!p.is_free_tier,
        firstProvider: p,
        providers: [p],
      })),
    ];
    cloudAvailGroups.sort((a, b) => {
      if (a.hasFree !== b.hasFree) return a.hasFree ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    const query = deferredSearchQuery.trim().toLowerCase();
    if (!query) {
      return {
        localConfigured: localConf,
        localAvailable: localAvail,
        cloudConfiguredGrouped: cloudResult.grouped,
        cloudConfiguredUngrouped: cloudResult.ungrouped,
        cloudAvailableGroups: cloudAvailGroups,
      };
    }

    const matchProvider = (p: ProviderInfo) =>
      p.name.toLowerCase().includes(query) ||
      (p.provider_group_name || "").toLowerCase().includes(query) ||
      (p.provider_variant || "").toLowerCase().includes(query);

    const filterGroups = (
      groups: ReturnType<typeof groupProviders>["grouped"],
    ) =>
      groups
        .map((g) => ({
          ...g,
          providers: g.providers.filter(matchProvider),
        }))
        .filter(
          (g) =>
            g.providers.length > 0 ||
            g.groupName.toLowerCase().includes(query),
        );

    return {
      localConfigured: localConf.filter(matchProvider),
      localAvailable: localAvail.filter(matchProvider),
      cloudConfiguredGrouped: filterGroups(cloudResult.grouped),
      cloudConfiguredUngrouped:
        cloudResult.ungrouped.filter(matchProvider),
      cloudAvailableGroups: cloudAvailGroups.filter(
        (g) =>
          g.name.toLowerCase().includes(query) ||
          g.firstProvider.name.toLowerCase().includes(query),
      ),
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
            <div className={styles.providersBlock}>
              <div
                className={styles.llmSectionHeader}
                onClick={() => setLlmCollapsed(!llmCollapsed)}
              >
                <PageHeader
                  current={t("models.defaultLlm")}
                  className={styles.providersPageHeader}
                />
                <DownOutlined
                  className={[
                    styles.defaultLlmChevron,
                    llmCollapsed ? "" : styles.defaultLlmChevronOpen,
                  ].join(" ")}
                />
              </div>
              {!llmCollapsed && (
                <ModelsSection
                  providers={providers}
                  activeModels={activeModels}
                  onSaved={fetchAll}
                />
              )}
            </div>
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

              {/* ---- Local & Custom Section ---- */}
              <div className={styles.providerGroup}>
                <h4 className={styles.providerGroupTitle}>
                  {t("models.localCustomGroup")}
                </h4>
                {localConfigured.length > 0 && (
                  <>
                    <h5 className={styles.subSectionTitle}>
                      {t("models.configuredGroup")}
                    </h5>
                    <div className={styles.providerCards}>
                      {renderProviderCards(localConfigured)}
                    </div>
                  </>
                )}
                {localAvailable.length > 0 && (
                  <>
                    <h5 className={styles.subSectionTitle}>
                      {t("models.availableGroup")}
                    </h5>
                    <div className={styles.availableGrid}>
                      {localAvailable.map((provider) => (
                        <div
                          key={provider.id}
                          className={styles.availableItem}
                          onClick={() => handleOpenConfig(provider)}
                        >
                          <ProviderIcon
                            providerId={provider.id}
                            size={24}
                          />
                          <span className={styles.availableItemName}>
                            {provider.name}
                          </span>
                          <span className={styles.availableItemAction}>
                            {t("models.configureAction")}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {/* ---- Cloud Section ---- */}
              <div className={styles.providerGroup}>
                <h4 className={styles.providerGroupTitle}>
                  {t("models.cloudGroup")}
                </h4>

                {cloudConfiguredGrouped.length > 0 ||
                cloudConfiguredUngrouped.length > 0 ? (
                  <>
                    <h5 className={styles.subSectionTitle}>
                      {t("models.configuredGroup")}
                      <span className={styles.configuredCount}>
                        {cloudConfiguredGrouped.reduce(
                          (n, g) => n + g.providers.length,
                          0,
                        ) + cloudConfiguredUngrouped.length}{" "}
                        {t("models.configuredOnline")}
                      </span>
                    </h5>
                    <div className={styles.providerCards}>
                      {cloudConfiguredGrouped.map((group) => (
                        <ProviderGroupCard
                          key={group.groupKey}
                          group={group}
                          onSaved={refreshProvidersSilently}
                          onOpenConfig={handleOpenConfig}
                          onOpenModels={handleOpenModels}
                        />
                      ))}
                      {renderProviderCards(cloudConfiguredUngrouped)}
                    </div>
                  </>
                ) : (
                  <div className={styles.emptyConfigured}>
                    <p>{t("models.noConfigured")}</p>
                    <Button
                      type="primary"
                      onClick={() => {
                        document
                          .getElementById("available-providers")
                          ?.scrollIntoView({ behavior: "smooth" });
                      }}
                    >
                      {t("models.goConfigureBtn")}
                    </Button>
                  </div>
                )}

                {cloudAvailableGroups.length > 0 && (
                  <div id="available-providers">
                    <h5 className={styles.subSectionTitle}>
                      {t("models.availableGroup")}
                      <span className={styles.availableHint}>
                        {t("models.clickToConfigure")}
                      </span>
                    </h5>
                    <div className={styles.availableGrid}>
                      {cloudAvailableGroups.map((g) => (
                        <div
                          key={g.key}
                          className={styles.availableItem}
                          onClick={() => {
                            if (g.providers.length > 1) {
                              setVariantSelectGroup(g);
                            } else {
                              handleOpenConfig(g.firstProvider);
                            }
                          }}
                        >
                          <ProviderIcon
                            providerId={g.firstProvider.id}
                            size={24}
                          />
                          <span
                            className={styles.availableItemName}
                          >
                            {g.name}
                          </span>
                          {g.hasFree && (
                            <span className={styles.freeTag}>
                              FREE
                            </span>
                          )}
                          <span
                            className={
                              styles.availableItemAction
                            }
                          >
                            {t("models.configureAction")}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
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

            <Modal
              open={!!variantSelectGroup}
              title={t("models.selectVariant", {
                name: variantSelectGroup?.name || "",
              })}
              footer={null}
              onCancel={() => setVariantSelectGroup(null)}
              destroyOnClose
            >
              <div className={styles.variantList}>
                {variantSelectGroup?.providers.map((p) => (
                  <div
                    key={p.id}
                    className={styles.variantItem}
                    onClick={() => {
                      setVariantSelectGroup(null);
                      handleOpenConfig(p);
                    }}
                  >
                    <ProviderIcon providerId={p.id} size={24} />
                    <span className={styles.variantItemName}>
                      {p.name}
                    </span>
                    {p.is_free_tier && (
                      <span className={styles.freeTag}>FREE</span>
                    )}
                  </div>
                ))}
              </div>
            </Modal>
          </div>
        </>
      )}
    </div>
  );
}

export default ModelsPage;
