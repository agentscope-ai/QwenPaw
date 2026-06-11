import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Dropdown, Spin, Tooltip, Modal } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  CheckOutlined,
  LoadingOutlined,
  SearchOutlined,
  CloseCircleFilled,
  DownOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { AlertTriangle, Link as LinkIcon, Settings } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import type { ProviderInfo, ActiveModelsInfo } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { OAuthConfirmModal } from "./OAuthConfirmModal";
import styles from "./index.module.less";

interface EligibleProvider {
  id: string;
  name: string;
  base_url?: string;
  models: ProviderInfo["models"];
  is_free_tier?: boolean;
  supports_oauth?: boolean;
  oauth_connected?: boolean;
  has_api_key?: boolean;
  require_api_key?: boolean;
}

export default function ModelSelector() {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"pro" | "free">(
    () =>
      (localStorage.getItem("qwenpaw_model_selector_tab") as "pro" | "free") ||
      "pro",
  );
  const [collapsedProviders, setCollapsedProviders] = useState<Set<string>>(
    () => {
      try {
        const raw = localStorage.getItem("qwenpaw_model_selector_collapsed");
        return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
      } catch {
        return new Set();
      }
    },
  );
  const savingRef = useRef(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();

  const [showMoreFree, setShowMoreFree] = useState(false);
  const moreContentRef = useRef<HTMLDivElement>(null);
  const [expandedModels, setExpandedModels] = useState<Record<string, number>>(
    {},
  );

  // OAuth modal state
  const [oauthModal, setOauthModal] = useState<{
    open: boolean;
    providerId: string;
    providerName: string;
    pendingModelId: string;
  }>({ open: false, providerId: "", providerName: "", pendingModelId: "" });

  // Navigate-to-config confirmation state
  const [configNavModal, setConfigNavModal] = useState<{
    open: boolean;
    providerId: string;
    providerName: string;
  }>({ open: false, providerId: "", providerName: "" });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [provData, activeData] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels({
          scope: "effective",
          agent_id: selectedAgent,
        }),
      ]);
      if (Array.isArray(provData)) setProviders(provData);
      if (activeData) setActiveModels(activeData);
    } catch (err) {
      console.error("ModelSelector: failed to load data", err);
    } finally {
      setLoading(false);
    }
  }, [selectedAgent]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Re-sync active model whenever the route switches back to /chat
  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    const prev = prevPathRef.current;
    const curr = location.pathname;
    prevPathRef.current = curr;
    const comingToChat = curr.startsWith("/chat") && !prev.startsWith("/chat");
    if (comingToChat) {
      providerApi
        .getActiveModels({
          scope: "effective",
          agent_id: selectedAgent,
        })
        .then((activeData) => {
          if (activeData) setActiveModels(activeData);
        })
        .catch(() => {});
    }
  }, [location.pathname, selectedAgent]);

  // Eligible providers: configured + has models, OR is_free_tier
  const eligibleProviders: EligibleProvider[] = providers
    .filter((p) => {
      const hasModels =
        (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
      // Free tier: always show (OAuth or needs-key)
      if (p.is_free_tier) return true;
      if (!hasModels) return false;
      if (p.require_api_key === false) return !!p.base_url;
      if (p.is_custom) return !!p.base_url;
      if (p.require_api_key ?? true) return !!p.api_key;
      return true;
    })
    .map((p) => ({
      id: p.id,
      name: p.name,
      base_url: p.base_url,
      models: [...(p.models ?? []), ...(p.extra_models ?? [])],
      is_free_tier: p.is_free_tier,
      supports_oauth: p.supports_oauth,
      oauth_connected: p.oauth_connected,
      has_api_key: !!p.api_key,
      require_api_key: p.require_api_key,
    }));

  // Split by model-level is_free, not provider-level is_free_tier
  const { freeProviders, proProviders } = useMemo(() => {
    const freeMap = new Map<string, EligibleProvider>();
    const proMap = new Map<string, EligibleProvider>();
    for (const p of eligibleProviders) {
      const freeModels = p.models.filter((m) => m.is_free);
      const proModels = p.models.filter((m) => !m.is_free);
      if (freeModels.length > 0 || (p.is_free_tier && p.models.length === 0)) {
        freeMap.set(p.id, { ...p, models: freeModels });
      }
      // PRO: show paid models when API key is configured, or when
      // the provider doesn't require an API key (e.g. ollama, lmstudio)
      if (
        proModels.length > 0 &&
        (p.has_api_key || p.require_api_key === false)
      ) {
        proMap.set(p.id, { ...p, models: proModels });
      }
    }
    return {
      freeProviders: [...freeMap.values()],
      proProviders: [...proMap.values()],
    };
  }, [eligibleProviders]);

  // Filter by search query
  const trimmedSearch = searchQuery.trim();
  const filterProviders = (list: EligibleProvider[]) => {
    if (!trimmedSearch) return list;
    const query = trimmedSearch.toLowerCase();
    return list
      .map((p) => ({
        ...p,
        models: p.models.filter(
          (m) =>
            (m.name || m.id).toLowerCase().includes(query) ||
            p.name.toLowerCase().includes(query),
        ),
      }))
      .filter(
        (p) => p.models.length > 0 || p.name.toLowerCase().includes(query),
      );
  };

  const filteredFree = filterProviders(freeProviders);
  const filteredPro = filterProviders(proProviders);

  // Focus search input when dropdown opens; clear query when closes
  useEffect(() => {
    if (open) {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    } else {
      setSearchQuery("");
    }
  }, [open]);

  const activeProviderId = activeModels?.active_llm?.provider_id;
  const activeModelId = activeModels?.active_llm?.model;

  // Display label for trigger button
  const activeModelName = (() => {
    if (!activeProviderId || !activeModelId)
      return t("modelSelector.selectModel");
    for (const p of eligibleProviders) {
      if (p.id === activeProviderId) {
        const m = p.models.find((m) => m.id === activeModelId);
        if (m) return m.name || m.id;
      }
    }
    return activeModelId;
  })();

  const showActiveProviderIcon = Boolean(activeProviderId);

  const handleOpenChange = useCallback(
    async (next: boolean) => {
      setOpen(next);
      if (next) {
        try {
          const activeData = await providerApi.getActiveModels({
            scope: "effective",
            agent_id: selectedAgent,
          });
          if (activeData) setActiveModels(activeData);
        } catch {
          // ignore
        }
      }
    },
    [selectedAgent],
  );

  const handleSelect = async (providerId: string, modelId: string) => {
    if (savingRef.current) return;
    if (providerId === activeProviderId && modelId === activeModelId) {
      setOpen(false);
      return;
    }

    const targetProvider = eligibleProviders.find(
      (provider) => provider.id === providerId,
    );
    const targetModel = targetProvider?.models.find(
      (model) => model.id === modelId,
    );

    // Check if OAuth is needed
    if (
      targetProvider?.supports_oauth &&
      !targetProvider.has_api_key &&
      !targetProvider.oauth_connected
    ) {
      setOpen(false);
      setOauthModal({
        open: true,
        providerId,
        providerName: targetProvider.name,
        pendingModelId: modelId,
      });
      return;
    }

    setOpen(false);

    if (targetProvider && targetModel) {
      const confirmed = await confirmFreeModelSwitch({
        provider: targetProvider,
        model: targetModel,
        t,
      });
      if (!confirmed) return;
    }

    savingRef.current = true;
    setSaving(true);
    try {
      await providerApi.setActiveLlm({
        provider_id: providerId,
        model: modelId,
        scope: "agent",
        agent_id: selectedAgent,
      });
      setActiveModels({
        active_llm: { provider_id: providerId, model: modelId },
      });
      window.dispatchEvent(new CustomEvent("model-switched"));
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("modelSelector.switchFailed");
      message.error(msg);
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  const handleOAuthSuccess = async () => {
    setOauthModal((prev) => ({ ...prev, open: false }));
    await fetchData();
    if (oauthModal.providerId && oauthModal.pendingModelId) {
      savingRef.current = true;
      setSaving(true);
      try {
        await providerApi.setActiveLlm({
          provider_id: oauthModal.providerId,
          model: oauthModal.pendingModelId,
          scope: "agent",
          agent_id: selectedAgent,
        });
        setActiveModels({
          active_llm: {
            provider_id: oauthModal.providerId,
            model: oauthModal.pendingModelId,
          },
        });
        window.dispatchEvent(new CustomEvent("model-switched"));
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : t("modelSelector.switchFailed");
        message.error(msg);
      } finally {
        setSaving(false);
        savingRef.current = false;
      }
    }
  };

  const handleOAuthConnect = (provider: EligibleProvider) => {
    setOpen(false);
    setOauthModal({
      open: true,
      providerId: provider.id,
      providerName: provider.name,
      pendingModelId: "",
    });
  };

  const toggleProviderCollapse = (providerId: string) => {
    setCollapsedProviders((prev) => {
      const next = new Set(prev);
      if (next.has(providerId)) {
        next.delete(providerId);
      } else {
        next.add(providerId);
      }
      localStorage.setItem(
        "qwenpaw_model_selector_collapsed",
        JSON.stringify([...next]),
      );
      return next;
    });
  };

  const renderProviderModels = (provider: EligibleProvider) => {
    const needsOAuth =
      provider.supports_oauth &&
      !provider.has_api_key &&
      !provider.oauth_connected;
    const isCollapsed = collapsedProviders.has(provider.id);
    const visibleCount = expandedModels[provider.id] ?? 5;
    const visibleModels = provider.models.slice(0, visibleCount);
    const remaining = provider.models.length - visibleCount;
    const hasMore = remaining > 0;

    return (
      <div key={provider.id} className={styles.providerGroup}>
        <div
          className={styles.providerHeader}
          onClick={() => toggleProviderCollapse(provider.id)}
        >
          <ProviderIcon providerId={provider.id} size={16} />
          <span className={styles.providerHeaderName}>{provider.name}</span>
          {needsOAuth && (
            <AlertTriangle size={12} className={styles.oauthWarningIcon} />
          )}
          <span className={styles.collapseIcon}>
            {isCollapsed ? <DownOutlined /> : <UpOutlined />}
          </span>
        </div>
        {!isCollapsed && (
          <>
            {visibleModels.map((model) => {
              const isActive =
                provider.id === activeProviderId && model.id === activeModelId;
              return (
                <div
                  key={model.id}
                  className={[
                    styles.modelItem,
                    isActive ? styles.modelItemActive : "",
                  ].join(" ")}
                  onClick={() => handleSelect(provider.id, model.id)}
                >
                  <span className={styles.modelName}>
                    {model.name || model.id}
                  </span>
                  <div className={styles.modelTags}>
                    {needsOAuth && (
                      <AlertTriangle
                        size={12}
                        className={styles.oauthWarningIcon}
                      />
                    )}
                    {model.is_free && !needsOAuth && (
                      <span className={styles.freeTag}>
                        {t("modelSelector.free")}
                      </span>
                    )}
                    {(model.supports_image || model.supports_multimodal) && (
                      <span className={styles.visionTag}>
                        {t("modelSelector.vision")}
                      </span>
                    )}
                    {isActive && <CheckOutlined className={styles.checkIcon} />}
                  </div>
                </div>
              );
            })}
            {hasMore && (
              <div
                className={styles.viewMore}
                onClick={(e) => {
                  e.stopPropagation();
                  setExpandedModels((prev) => ({
                    ...prev,
                    [provider.id]: visibleCount + 10,
                  }));
                }}
              >
                {t("modelSelector.viewMore", {
                  count: Math.min(10, remaining),
                })}
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  const renderOAuthConnectEntry = (provider: EligibleProvider) => {
    const isConnected = provider.has_api_key || provider.oauth_connected;
    if (isConnected && provider.models.length > 0) return null;

    return (
      <div key={provider.id} className={styles.providerGroup}>
        <div className={styles.providerHeader}>
          <ProviderIcon providerId={provider.id} size={16} />
          <span className={styles.providerHeaderName}>{provider.name}</span>
        </div>
        {isConnected && provider.models.length === 0 ? (
          <div className={styles.connectHint}>
            {t("modelSelector.noModelsDiscovered")}
          </div>
        ) : (
          <div
            className={styles.connectEntry}
            onClick={() => handleOAuthConnect(provider)}
          >
            <LinkIcon size={14} className={styles.connectIcon} />
            <span>
              {t("modelSelector.connectToUse", { provider: provider.name })}
            </span>
          </div>
        )}
      </div>
    );
  };

  const renderApiKeyEntry = (provider: EligibleProvider) => {
    return (
      <div key={provider.id} className={styles.providerGroup}>
        <div className={styles.providerHeader}>
          <ProviderIcon providerId={provider.id} size={16} />
          <span className={styles.providerHeaderName}>{provider.name}</span>
        </div>
        <div
          className={styles.connectEntry}
          onClick={() => {
            setOpen(false);
            setConfigNavModal({
              open: true,
              providerId: provider.id,
              providerName: provider.name,
            });
          }}
        >
          <Settings size={14} className={styles.connectIcon} />
          <span>
            {t("modelSelector.configureApiKey", { provider: provider.name })}
          </span>
        </div>
      </div>
    );
  };

  const renderFreeTab = () => {
    if (loading) {
      return (
        <div className={styles.spinWrapper}>
          <Spin size="small" />
        </div>
      );
    }

    // Providers already usable (has key or doesn't need one)
    const readyProviders = filteredFree.filter(
      (p) =>
        p.models.length > 0 && (p.has_api_key || p.require_api_key === false),
    );
    // OAuth providers not yet connected
    const oauthOnlyProviders = filteredFree.filter(
      (p) => p.supports_oauth && !p.has_api_key && !p.oauth_connected,
    );
    // Providers that need API key (not OAuth, no key yet)
    const needsKeyProviders = filteredFree.filter(
      (p) => !p.supports_oauth && !p.has_api_key && p.require_api_key !== false,
    );

    const hasAny =
      readyProviders.length > 0 ||
      oauthOnlyProviders.length > 0 ||
      needsKeyProviders.length > 0;

    if (!hasAny) {
      return (
        <div className={styles.emptyTip}>
          {trimmedSearch
            ? t("modelSelector.noModelsFound")
            : t("modelSelector.noFreeModels")}
        </div>
      );
    }

    return (
      <>
        <div className={styles.freeBanner}>
          <AlertTriangle size={14} className={styles.freeBannerIcon} />
          <span>{t("modelSelector.freeBannerText")}</span>
        </div>
        {readyProviders.map(renderProviderModels)}
        {oauthOnlyProviders.map(renderOAuthConnectEntry)}
        {needsKeyProviders.length > 0 && (
          <>
            <div
              className={styles.moreToggle}
              onClick={() => {
                setShowMoreFree((v) => {
                  if (!v) {
                    setTimeout(() => {
                      moreContentRef.current?.scrollIntoView({
                        behavior: "smooth",
                        block: "nearest",
                      });
                    }, 50);
                  }
                  return !v;
                });
              }}
            >
              <span>{t("modelSelector.moreProviders")}</span>
              {showMoreFree ? <UpOutlined /> : <DownOutlined />}
            </div>
            {showMoreFree && (
              <div ref={moreContentRef} className={styles.moreContent}>
                {needsKeyProviders.map(renderApiKeyEntry)}
              </div>
            )}
          </>
        )}
      </>
    );
  };

  const renderProTab = () => {
    if (loading) {
      return (
        <div className={styles.spinWrapper}>
          <Spin size="small" />
        </div>
      );
    }

    if (filteredPro.length === 0) {
      return (
        <div className={styles.emptyTip}>
          {trimmedSearch
            ? t("modelSelector.noModelsFound")
            : t("modelSelector.noConfiguredModels")}
        </div>
      );
    }

    return (
      <>
        <div className={styles.proBanner}>
          <span>{t("modelSelector.proBannerText")}</span>
        </div>
        {filteredPro.map(renderProviderModels)}
      </>
    );
  };

  const dropdownContent = (
    <div className={styles.panel}>
      <div className={styles.searchWrapper}>
        <SearchOutlined className={styles.searchIcon} />
        <input
          ref={searchInputRef}
          className={styles.searchInput}
          placeholder={t("modelSelector.searchModels")}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <CloseCircleFilled
            className={styles.searchClear}
            onClick={(e) => {
              e.stopPropagation();
              setSearchQuery("");
              searchInputRef.current?.focus();
            }}
          />
        )}
      </div>

      <div className={styles.tabBar}>
        <button
          className={[
            styles.tabButton,
            activeTab === "pro" ? styles.tabButtonActive : "",
          ].join(" ")}
          onClick={() => {
            setActiveTab("pro");
            localStorage.setItem("qwenpaw_model_selector_tab", "pro");
          }}
        >
          PRO
        </button>
        <button
          className={[
            styles.tabButton,
            activeTab === "free" ? styles.tabButtonActive : "",
          ].join(" ")}
          onClick={() => {
            setActiveTab("free");
            localStorage.setItem("qwenpaw_model_selector_tab", "free");
          }}
        >
          FREE
        </button>
      </div>

      <div className={styles.listContainer}>
        {activeTab === "free" ? renderFreeTab() : renderProTab()}
      </div>
    </div>
  );

  return (
    <>
      <Dropdown
        open={open}
        onOpenChange={handleOpenChange}
        popupRender={() => dropdownContent}
        trigger={["click"]}
        placement="bottomLeft"
      >
        <Tooltip title={t("chat.modelSelectTooltip")} mouseEnterDelay={0.5}>
          <div
            className={[styles.trigger, open ? styles.triggerActive : ""].join(
              " ",
            )}
          >
            {saving && (
              <LoadingOutlined style={{ fontSize: 11, color: "#FF7F16" }} />
            )}
            {showActiveProviderIcon && activeProviderId && (
              <ProviderIcon providerId={activeProviderId} size={16} />
            )}
            <span className={styles.triggerName}>{activeModelName}</span>
            {open ? <UpOutlined /> : <DownOutlined />}
          </div>
        </Tooltip>
      </Dropdown>

      <Modal
        open={configNavModal.open}
        title={t("modelSelector.configureApiKeyTitle")}
        onCancel={() => setConfigNavModal((prev) => ({ ...prev, open: false }))}
        onOk={() => {
          setConfigNavModal((prev) => ({ ...prev, open: false }));
          navigate(`/models?provider=${configNavModal.providerId}`);
        }}
        okText={t("modelSelector.goToConfigure")}
        cancelText={t("common.cancel")}
      >
        <p>
          {t("modelSelector.configureApiKeyConfirm", {
            provider: configNavModal.providerName,
          })}
        </p>
      </Modal>

      <OAuthConfirmModal
        open={oauthModal.open}
        providerId={oauthModal.providerId}
        providerName={oauthModal.providerName}
        onSuccess={handleOAuthSuccess}
        onCancel={() => setOauthModal((prev) => ({ ...prev, open: false }))}
      />
    </>
  );
}
