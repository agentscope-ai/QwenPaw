import {
  useState,
  useEffect,
  useCallback,
  useId,
  useRef,
  useMemo,
} from "react";
import { Dropdown, Spin, Tooltip, Modal } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Link as LinkIcon,
  Eye,
  GitBranch,
  LoaderCircle,
  Search,
  Settings,
  XCircle,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { ActiveModelsInfo } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { useTurnUsageStore } from "../turnUsageStore";
import { OAuthConfirmModal } from "./OAuthConfirmModal";
import { AgentModelSettings } from "./AgentModelSettings";
import { CandidateModelSection } from "./CandidateModelSection";
import { modelSelectorApi } from "./modelSelectorApi";
import {
  buildDiscoveryCandidates,
  buildEligibleProviders,
  buildHiddenCandidates,
  modelKey,
  splitProvidersByTier,
} from "./modelSelectorModels";
import type { CandidateModel, EligibleProvider } from "./modelSelectorModels";
import { useModelSelectorData } from "./useModelSelectorData";
import styles from "./index.module.less";

/** Sync Chat context ring with the active model's effective window. */
function publishActiveMaxInputLength(
  effectiveMaxInputLength: number | null | undefined,
): void {
  const maxInputLength =
    typeof effectiveMaxInputLength === "number"
      ? effectiveMaxInputLength
      : null;
  useTurnUsageStore.getState().setActiveMaxInputLength(maxInputLength);
  if (typeof maxInputLength === "number" && maxInputLength > 0) {
    window.dispatchEvent(
      new CustomEvent("model-switched", {
        detail: { maxInputLength },
      }),
    );
  }
}

const RECENT_STORAGE_KEY = "qwenpaw_model_selector_recent";
const DEFAULT_VISIBLE_MODELS = 5;
const VIEW_MORE_STEP = 20;

interface ModelSelectorProps {
  showAdvancedModelControls?: boolean;
}

function readStoredModelKeys(key: string): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value)
      ? value.filter((item) => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

export default function ModelSelector({
  showAdvancedModelControls = false,
}: ModelSelectorProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [addingKey, setAddingKey] = useState<string | null>(null);
  const [visibilityKey, setVisibilityKey] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"pro" | "free">(
    () =>
      (localStorage.getItem("qwenpaw_model_selector_tab") as "pro" | "free") ||
      "pro",
  );
  const [collapsedProviders, setCollapsedProviders] = useState<Set<string>>(
    () => new Set(),
  );
  const savingRef = useRef(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const panelId = useId();
  const proTabId = useId();
  const freeTabId = useId();
  const tabPanelId = useId();
  const moreProvidersId = useId();
  const candidateModelsId = useId();
  const location = useLocation();
  const navigate = useNavigate();
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();
  const activationRevisionRef = useRef(0);
  const selectedAgentRef = useRef(selectedAgent);
  selectedAgentRef.current = selectedAgent;

  const [showMoreFree, setShowMoreFree] = useState(false);
  const moreContentRef = useRef<HTMLDivElement>(null);
  const [expandedModels, setExpandedModels] = useState<Record<string, number>>(
    {},
  );
  const [showCandidateModels, setShowCandidateModels] = useState(false);
  const [recentModelKeys, setRecentModelKeys] = useState<string[]>(() =>
    readStoredModelKeys(RECENT_STORAGE_KEY),
  );

  // Mobile viewport detection for dropdown placement
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 768);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 768px)");
    const handler = (e: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(e.matches);
    };
    handler(media);
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }, []);

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

  const handleActiveModels = useCallback((activeData: ActiveModelsInfo) => {
    publishActiveMaxInputLength(activeData.effective_max_input_length);
  }, []);
  const {
    activeModels,
    fetchData,
    loading,
    loadError,
    providers,
    refreshActiveModels,
    setActiveModels,
    setProviders,
  } = useModelSelectorData({
    agentId: selectedAgent,
    onActiveModels: handleActiveModels,
  });

  useEffect(() => {
    activationRevisionRef.current += 1;
    savingRef.current = false;
    setSaving(false);
  }, [selectedAgent]);

  // Re-sync active model whenever the route switches back to /chat
  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    const prev = prevPathRef.current;
    const curr = location.pathname;
    prevPathRef.current = curr;
    const comingToChat = curr.startsWith("/chat") && !prev.startsWith("/chat");
    if (comingToChat) {
      void refreshActiveModels().catch(() => {});
    }
  }, [location.pathname, refreshActiveModels]);

  // Eligible providers: configured + has models, OR is_free_tier
  const eligibleProviders = useMemo(
    () => buildEligibleProviders(providers),
    [providers],
  );

  // Free providers appear in both tabs; other providers use model-level tags.
  const { freeProviders, proProviders } = useMemo(() => {
    return splitProvidersByTier(eligibleProviders);
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
  const actualUsage = useTurnUsageStore((state) => state.snapshot?.usage);
  const fallbackModel = useMemo(() => {
    const providerId = actualUsage?.provider_id;
    const modelId = actualUsage?.model_name;
    if (
      !providerId ||
      !modelId ||
      (providerId === activeProviderId && modelId === activeModelId)
    ) {
      return null;
    }
    const provider = providers.find((item) => item.id === providerId);
    const model = [
      ...(provider?.models ?? []),
      ...(provider?.extra_models ?? []),
    ].find((item) => item.id === modelId);
    return {
      providerId,
      providerName: provider?.name || providerId,
      label: model?.name || modelId,
    };
  }, [actualUsage, activeModelId, activeProviderId, providers]);

  const discoveryCandidates = useMemo(
    () => buildDiscoveryCandidates(providers),
    [providers],
  );

  const hiddenCandidates = useMemo(
    () => buildHiddenCandidates(providers),
    [providers],
  );

  const visibleCandidates = useMemo(() => {
    const query = trimmedSearch.toLowerCase();
    return discoveryCandidates.filter(({ provider, model }) => {
      const matchesQuery = query
        ? model.id.toLowerCase().includes(query) ||
          model.name.toLowerCase().includes(query) ||
          provider.name.toLowerCase().includes(query)
        : true;
      if (!matchesQuery) return false;
      return activeTab === "free" ? Boolean(model.is_free) : !model.is_free;
    });
  }, [activeTab, discoveryCandidates, trimmedSearch]);
  const candidateModelsExpanded = Boolean(trimmedSearch) || showCandidateModels;

  const rankModels = useCallback(
    (list: EligibleProvider[]): EligibleProvider[] => {
      const ranked = list.flatMap((provider) =>
        provider.models.map((model) => ({ provider, model })),
      );
      ranked.sort((left, right) => {
        const leftKey = modelKey(left.provider.id, left.model.id);
        const rightKey = modelKey(right.provider.id, right.model.id);
        const score = (key: string, providerId: string, id: string) => {
          const recent = recentModelKeys.indexOf(key);
          if (recent >= 0) return recent - 200;
          if (providerId === activeProviderId && id === activeModelId)
            return -100;
          return 0;
        };
        return (
          score(leftKey, left.provider.id, left.model.id) -
          score(rightKey, right.provider.id, right.model.id)
        );
      });
      const grouped = new Map<string, EligibleProvider>();
      for (const item of ranked) {
        const current = grouped.get(item.provider.id);
        if (current) current.models.push(item.model);
        else
          grouped.set(item.provider.id, {
            ...item.provider,
            models: [item.model],
          });
      }
      return [...grouped.values()];
    },
    [activeModelId, activeProviderId, recentModelKeys],
  );

  const rememberRecent = (providerId: string, modelId: string) => {
    const key = modelKey(providerId, modelId);
    setRecentModelKeys((previous) => {
      const next = [key, ...previous.filter((item) => item !== key)].slice(
        0,
        5,
      );
      localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };

  // Display the active model metadata in the trigger button.
  const activeModel = (() => {
    if (!activeProviderId || !activeModelId) return null;
    const provider = eligibleProviders.find(
      (item) => item.id === activeProviderId,
    );
    return provider?.models.find((model) => model.id === activeModelId) ?? null;
  })();
  const activeModelName =
    activeModel?.name || activeModelId || t("modelSelector.selectModel");
  const activeModelIsFree = Boolean(activeModel?.is_free);

  const showActiveProviderIcon = Boolean(activeProviderId);

  // Marquee the trigger name on very narrow screens when it overflows.
  const triggerNameRef = useRef<HTMLSpanElement | null>(null);
  const triggerNameMeasureRef = useRef<HTMLSpanElement | null>(null);
  const [shouldMarquee, setShouldMarquee] = useState(false);

  useEffect(() => {
    const check = () => {
      const w = typeof window !== "undefined" ? window.innerWidth : 0;
      if (w > 480) {
        setShouldMarquee(false);
        return;
      }
      const containerWidth =
        triggerNameRef.current?.getBoundingClientRect().width ?? 0;
      const textWidth =
        triggerNameMeasureRef.current?.getBoundingClientRect().width ?? 0;
      // Small tolerance to avoid borderline jitter.
      setShouldMarquee(textWidth > containerWidth + 2);
    };

    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [activeModelName]);

  const handleOpenChange = useCallback(
    async (next: boolean) => {
      setOpen(next);
      if (next) {
        try {
          await refreshActiveModels();
        } catch {
          // ignore
        }
      }
    },
    [refreshActiveModels],
  );

  const activateModel = async (providerId: string, modelId: string) => {
    if (savingRef.current) return;
    if (providerId === activeProviderId && modelId === activeModelId) {
      setOpen(false);
      return;
    }

    const targetAgentId = selectedAgent;
    const activationRevision = ++activationRevisionRef.current;
    savingRef.current = true;
    setSaving(true);
    try {
      const updated = await modelSelectorApi.setActiveLlm({
        provider_id: providerId,
        model: modelId,
        scope: "agent",
        agent_id: targetAgentId,
      });
      if (
        activationRevision !== activationRevisionRef.current ||
        targetAgentId !== selectedAgentRef.current
      ) {
        return;
      }
      setActiveModels(
        updated?.active_llm
          ? updated
          : {
              ...updated,
              active_llm: { provider_id: providerId, model: modelId },
            },
      );
      publishActiveMaxInputLength(updated?.effective_max_input_length);
      rememberRecent(providerId, modelId);
    } catch (err) {
      if (
        activationRevision !== activationRevisionRef.current ||
        targetAgentId !== selectedAgentRef.current
      ) {
        return;
      }
      const msg =
        err instanceof Error ? err.message : t("modelSelector.switchFailed");
      message.error(msg);
    } finally {
      if (activationRevision === activationRevisionRef.current) {
        setSaving(false);
        savingRef.current = false;
      }
    }
  };

  const handleSelect = async (providerId: string, modelId: string) => {
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

    await activateModel(providerId, modelId);
  };

  const handleAddCandidate = async (candidate: CandidateModel) => {
    const key = modelKey(candidate.provider.id, candidate.model.id);
    if (addingKey) return;

    const confirmed = await confirmFreeModelSwitch({
      provider: candidate.provider,
      model: candidate.model,
      t,
    });
    if (!confirmed) return;

    setAddingKey(key);
    try {
      await modelSelectorApi.addModel(candidate.provider.id, {
        id: candidate.model.id,
        name: candidate.model.name || candidate.model.id,
        is_free: candidate.model.is_free,
        supports_multimodal: candidate.model.supports_multimodal,
        supports_image: candidate.model.supports_image,
        supports_video: candidate.model.supports_video,
        probe_source: candidate.model.probe_source,
      });
      await activateModel(candidate.provider.id, candidate.model.id);
      await fetchData();
    } catch (err) {
      const text =
        err instanceof Error ? err.message : t("modelSelector.addFailed");
      message.error(text);
    } finally {
      setAddingKey(null);
    }
  };

  const handleVisibility = async (
    candidate: CandidateModel,
    hidden: boolean,
  ) => {
    const key = modelKey(candidate.provider.id, candidate.model.id);
    if (visibilityKey) return;
    setVisibilityKey(key);
    try {
      const updated = await modelSelectorApi.setModelVisibility(
        candidate.provider.id,
        candidate.model.id,
        hidden,
      );
      setProviders((current) =>
        current.map((provider) =>
          provider.id === updated.id ? updated : provider,
        ),
      );
    } catch (err) {
      const text =
        err instanceof Error
          ? err.message
          : t("modelSelector.visibilityFailed");
      message.error(text);
    } finally {
      setVisibilityKey(null);
    }
  };

  const handleOAuthSuccess = async () => {
    const { providerId, pendingModelId } = oauthModal;
    setOauthModal({
      open: false,
      providerId: "",
      providerName: "",
      pendingModelId: "",
    });
    const refreshed = await fetchData();
    if (!providerId) return;

    if (pendingModelId) {
      const provider = refreshed?.providers?.find(
        (candidate) => candidate.id === providerId,
      );
      const resolvedModel = [
        ...(provider?.models ?? []),
        ...(provider?.extra_models ?? []),
      ].find((model) => model.id === pendingModelId);
      if (provider && resolvedModel) {
        await activateModel(provider.id, resolvedModel.id);
        return;
      }
      message.error(t("modelSelector.oauthModelUnavailable"));
    }

    navigate(`/models?provider=${providerId}&manageModels=true`);
  };

  const handleOAuthCancel = () => {
    setOauthModal({
      open: false,
      providerId: "",
      providerName: "",
      pendingModelId: "",
    });
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
      return next;
    });
  };

  const renderProviderModels = (
    provider: EligibleProvider,
    limitInitialModels = false,
  ) => {
    const needsOAuth =
      provider.supports_oauth &&
      !provider.has_api_key &&
      !provider.oauth_connected;
    const isCollapsed = collapsedProviders.has(provider.id);
    const shouldLimitModels = !trimmedSearch && limitInitialModels;
    const visibleCount = shouldLimitModels
      ? Math.min(
          expandedModels[provider.id] ?? DEFAULT_VISIBLE_MODELS,
          provider.models.length,
        )
      : provider.models.length;
    const visibleModels = provider.models.slice(0, visibleCount);
    const remaining = provider.models.length - visibleCount;
    const hasMore = remaining > 0;

    return (
      <div key={provider.id} className={styles.providerGroup}>
        <button
          type="button"
          className={styles.providerHeader}
          aria-expanded={!isCollapsed}
          onClick={() => toggleProviderCollapse(provider.id)}
        >
          <ProviderIcon providerId={provider.id} size={16} />
          <span className={styles.providerHeaderName} title={provider.name}>
            {provider.name}
          </span>
          {needsOAuth && (
            <AlertTriangle size={12} className={styles.oauthWarningIcon} />
          )}
          <span className={styles.collapseIcon}>
            {isCollapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
          </span>
        </button>
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
                >
                  <button
                    type="button"
                    className={styles.modelSelectButton}
                    disabled={saving}
                    aria-current={isActive ? "true" : undefined}
                    onClick={() => handleSelect(provider.id, model.id)}
                  >
                    <span
                      className={styles.modelName}
                      title={model.name || model.id}
                    >
                      {model.name || model.id}
                    </span>
                  </button>
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
                    {isActive && (
                      <Check size={14} className={styles.checkIcon} />
                    )}
                  </div>
                </div>
              );
            })}
            {hasMore && (
              <button
                type="button"
                className={styles.viewMore}
                onClick={(e) => {
                  e.stopPropagation();
                  setExpandedModels((prev) => ({
                    ...prev,
                    [provider.id]: Math.min(
                      visibleCount + VIEW_MORE_STEP,
                      provider.models.length,
                    ),
                  }));
                }}
              >
                {t("modelSelector.viewMore", {
                  count: Math.min(remaining, VIEW_MORE_STEP),
                })}
              </button>
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
          <span className={styles.providerHeaderName} title={provider.name}>
            {provider.name}
          </span>
        </div>
        {isConnected && provider.models.length === 0 ? (
          <div className={styles.connectHint}>
            {t("modelSelector.noModelsDiscovered")}
          </div>
        ) : (
          <button
            type="button"
            className={styles.connectEntry}
            onClick={() => handleOAuthConnect(provider)}
          >
            <LinkIcon size={14} className={styles.connectIcon} />
            <span>
              {t("modelSelector.connectToUse", { provider: provider.name })}
            </span>
          </button>
        )}
      </div>
    );
  };

  const renderApiKeyEntry = (provider: EligibleProvider) => {
    return (
      <div key={provider.id} className={styles.providerGroup}>
        <div className={styles.providerHeader}>
          <ProviderIcon providerId={provider.id} size={16} />
          <span className={styles.providerHeaderName} title={provider.name}>
            {provider.name}
          </span>
        </div>
        <button
          type="button"
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
        </button>
      </div>
    );
  };

  const renderFreeTab = () => {
    if (loading) {
      return (
        <div className={styles.spinWrapper} role="status">
          <Spin size="small" />
          <span>{t("modelSelector.loadingModels")}</span>
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
        <div className={styles.emptyTip} role="status">
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
        {rankModels(readyProviders).map((provider) =>
          renderProviderModels(provider, false),
        )}
        {oauthOnlyProviders.map(renderOAuthConnectEntry)}
        {needsKeyProviders.length > 0 && (
          <>
            <button
              type="button"
              className={styles.moreToggle}
              aria-expanded={showMoreFree}
              aria-controls={moreProvidersId}
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
              {showMoreFree ? (
                <ChevronUp size={12} />
              ) : (
                <ChevronDown size={12} />
              )}
            </button>
            {showMoreFree && (
              <div
                id={moreProvidersId}
                ref={moreContentRef}
                className={styles.moreContent}
              >
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
        <div className={styles.spinWrapper} role="status">
          <Spin size="small" />
          <span>{t("modelSelector.loadingModels")}</span>
        </div>
      );
    }

    if (filteredPro.length === 0) {
      return (
        <div className={styles.emptyTip} role="status">
          {trimmedSearch
            ? t("modelSelector.noModelsFound")
            : t("modelSelector.noConfiguredModels")}
        </div>
      );
    }

    return (
      <>
        {showAdvancedModelControls && (
          <div className={styles.proBanner}>
            <span>{t("modelSelector.proBannerText")}</span>
          </div>
        )}
        {rankModels(filteredPro).map((provider) =>
          renderProviderModels(provider, true),
        )}
      </>
    );
  };

  const dropdownContent = (
    <div id={panelId} className={styles.panel}>
      <div className={styles.searchWrapper}>
        <Search size={15} className={styles.searchIcon} />
        <input
          ref={searchInputRef}
          className={styles.searchInput}
          aria-label={t("modelSelector.searchModels")}
          placeholder={t("modelSelector.searchModels")}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <button
            type="button"
            className={styles.searchClear}
            aria-label={t("modelSelector.clearSearch")}
            onClick={(e) => {
              e.stopPropagation();
              setSearchQuery("");
              searchInputRef.current?.focus();
            }}
          >
            <XCircle size={15} />
          </button>
        )}
      </div>

      <div className={styles.tabBar} role="tablist">
        <button
          type="button"
          id={proTabId}
          role="tab"
          aria-selected={activeTab === "pro"}
          aria-controls={tabPanelId}
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
          type="button"
          id={freeTabId}
          role="tab"
          aria-selected={activeTab === "free"}
          aria-controls={tabPanelId}
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

      <div
        id={tabPanelId}
        className={styles.listContainer}
        role="tabpanel"
        aria-labelledby={activeTab === "free" ? freeTabId : proTabId}
      >
        {loadError && (
          <div className={styles.loadError} role="alert">
            <span>{t("modelSelector.partialLoadFailed")}</span>
            <button type="button" onClick={fetchData}>
              {t("modelSelector.retry")}
            </button>
          </div>
        )}
        {activeTab === "free" ? renderFreeTab() : renderProTab()}
        {showAdvancedModelControls && (
          <CandidateModelSection
            candidates={visibleCandidates}
            expanded={candidateModelsExpanded}
            controlsId={candidateModelsId}
            searchActive={Boolean(trimmedSearch)}
            addingKey={addingKey}
            visibilityKey={visibilityKey}
            t={t}
            onToggle={() => setShowCandidateModels((value) => !value)}
            onAdd={handleAddCandidate}
            onHide={(candidate) => handleVisibility(candidate, true)}
          />
        )}
        {showAdvancedModelControls &&
          !trimmedSearch &&
          hiddenCandidates.length > 0 && (
            <details className={styles.hiddenModels}>
              <summary>
                {t("modelSelector.hiddenModels", {
                  count: hiddenCandidates.length,
                })}
              </summary>
              {hiddenCandidates.map((candidate) => {
                const key = modelKey(candidate.provider.id, candidate.model.id);
                return (
                  <div key={key} className={styles.hiddenModelItem}>
                    <span title={candidate.model.name || candidate.model.id}>
                      {candidate.model.name || candidate.model.id}
                    </span>
                    <button
                      type="button"
                      aria-label={t("modelSelector.restoreModel")}
                      disabled={visibilityKey === key}
                      onClick={() => handleVisibility(candidate, false)}
                    >
                      <Eye size={14} />
                      {t("modelSelector.restore")}
                    </button>
                  </div>
                );
              })}
            </details>
          )}
        {showAdvancedModelControls && (
          <AgentModelSettings
            agentId={selectedAgent}
            providers={eligibleProviders}
            activeProviderId={activeProviderId}
            activeModelId={activeModelId}
          />
        )}
      </div>
    </div>
  );

  return (
    <>
      <Dropdown
        open={open}
        onOpenChange={handleOpenChange}
        popupRender={() => (
          <div style={{ transform: "translateY(0)" }}>{dropdownContent}</div>
        )}
        trigger={["click"]}
        placement={isMobile ? "bottomCenter" : "bottomLeft"}
      >
        <Tooltip title={t("chat.modelSelectTooltip")} mouseEnterDelay={0.5}>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={t("chat.modelSelectTooltip")}
            className={[styles.trigger, open ? styles.triggerActive : ""].join(
              " ",
            )}
          >
            {saving && <LoaderCircle size={12} className={styles.spinning} />}
            {showActiveProviderIcon && activeProviderId && (
              <ProviderIcon providerId={activeProviderId} size={16} />
            )}
            {showAdvancedModelControls && fallbackModel && (
              <Tooltip
                title={t("modelSelector.fallbackActive", {
                  provider: fallbackModel.providerName,
                  model: fallbackModel.label,
                })}
              >
                <span
                  className={styles.fallbackBadge}
                  aria-label={t("modelSelector.fallbackActive", {
                    provider: fallbackModel.providerName,
                    model: fallbackModel.label,
                  })}
                >
                  <ProviderIcon
                    providerId={fallbackModel.providerId}
                    size={13}
                  />
                  <GitBranch size={12} />
                  <span>{fallbackModel.label}</span>
                </span>
              </Tooltip>
            )}
            <span className={styles.triggerName} ref={triggerNameRef}>
              {shouldMarquee ? (
                <span className={styles.marquee}>{activeModelName}</span>
              ) : (
                activeModelName
              )}
            </span>
            {activeModelIsFree && (
              <span className={styles.freeTag}>{t("modelSelector.free")}</span>
            )}
            {/* Hidden span used to measure intrinsic text width. Placed
                outside .triggerName so it does not duplicate text for
                screen readers or testing-library queries. */}
            <span
              ref={triggerNameMeasureRef}
              aria-hidden="true"
              style={{
                position: "absolute",
                visibility: "hidden",
                whiteSpace: "nowrap",
                pointerEvents: "none",
              }}
            >
              {activeModelName}
            </span>
          </button>
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
        onCancel={handleOAuthCancel}
      />
    </>
  );
}
