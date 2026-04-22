import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Dropdown, Spin, Tooltip } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  CheckOutlined,
  LoadingOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { SparkDownLine } from "@agentscope-ai/icons";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import type {
  ProviderInfo,
  ActiveModelsInfo,
  RoutingConfig,
  RoutingMode,
  ModelSlotConfig,
} from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import {
  hasConfiguredRoutingSlot,
  isLoopbackBaseUrl,
} from "../../../utils/routing";
import { providerIcon } from "../../Settings/Models/components/providerIcon";
import RoutingSection, { SlotKind } from "./RoutingSection";
import styles from "./index.module.less";

interface EligibleProvider {
  id: string;
  name: string;
  base_url?: string;
  isLocal: boolean;
  models: Array<{ id: string; name: string; is_free?: boolean }>;
}

const EMPTY_LOCAL_SLOT: ModelSlotConfig = {
  provider_id: "",
  model: "",
};

function getConfiguredSlot(
  slot?: ModelSlotConfig | null,
): ModelSlotConfig | null {
  return hasConfiguredRoutingSlot(slot) ? slot : null;
}

function hasRoutingOverride(config?: RoutingConfig | null): boolean {
  return Boolean(
    config &&
      (config.enabled ||
        hasConfiguredRoutingSlot(config.local) ||
        hasConfiguredRoutingSlot(config.cloud)),
  );
}

export default function ModelSelector() {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [routingConfig, setRoutingConfig] = useState<RoutingConfig | null>(
    null,
  );
  const [globalRouting, setGlobalRouting] = useState<RoutingConfig | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const savingRef = useRef(false);
  const location = useLocation();
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();

  const loadData = useCallback(
    async (includeProviders: boolean) => {
      if (includeProviders) {
        setLoading(true);
      }
      try {
        const [provData, activeData, routingData, globalRoutingData] =
          await Promise.all([
            includeProviders
              ? providerApi.listProviders()
              : Promise.resolve<ProviderInfo[] | null>(null),
            providerApi.getActiveModels({
              scope: "effective",
              agent_id: selectedAgent,
            }),
            providerApi.getRoutingConfig({
              agent_id: selectedAgent,
            }),
            providerApi.getRoutingConfig(),
          ]);

        if (includeProviders && Array.isArray(provData)) {
          setProviders(provData);
        }
        if (activeData) setActiveModels(activeData);
        if (routingData) setRoutingConfig(routingData);
        if (globalRoutingData) setGlobalRouting(globalRoutingData);
      } catch (err) {
        console.error("ModelSelector: failed to load data", err);
      } finally {
        if (includeProviders) {
          setLoading(false);
        }
      }
    },
    [selectedAgent],
  );

  useEffect(() => {
    void loadData(true);
  }, [loadData]);

  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    const prev = prevPathRef.current;
    const curr = location.pathname;
    prevPathRef.current = curr;
    const comingToChat = curr.startsWith("/chat") && !prev.startsWith("/chat");
    if (comingToChat) {
      void loadData(true);
    }
  }, [loadData, location.pathname]);

  const eligibleProviders: EligibleProvider[] = useMemo(
    () =>
      providers
        .filter((p) => {
          const hasModels =
            (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
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
          isLocal: Boolean(p.is_local || isLoopbackBaseUrl(p.base_url)),
          models: [...(p.models ?? []), ...(p.extra_models ?? [])],
        })),
    [providers],
  );

  const localProviders = useMemo(
    () => eligibleProviders.filter((provider) => provider.isLocal),
    [eligibleProviders],
  );
  const cloudProviders = useMemo(
    () => eligibleProviders.filter((provider) => !provider.isLocal),
    [eligibleProviders],
  );

  const activeProviderId = activeModels?.active_llm?.provider_id;
  const activeModelId = activeModels?.active_llm?.model;
  const routingEnabled = Boolean(routingConfig?.enabled);
  const routingMode: RoutingMode = routingConfig?.mode ?? "local_first";
  const routingBase = hasRoutingOverride(routingConfig)
    ? routingConfig
    : globalRouting;
  const effectiveLocalSlot = getConfiguredSlot(routingBase?.local);
  const effectiveCloudSlot = getConfiguredSlot(routingBase?.cloud);
  const routingFeatureReady = Boolean(effectiveLocalSlot && effectiveCloudSlot);
  const activeModelSlot =
    !routingEnabled && activeProviderId && activeModelId
      ? {
          provider_id: activeProviderId,
          model: activeModelId,
        }
      : null;

  const resolveProviderLabel = useCallback(
    (providerId?: string | null) => {
      if (!providerId) return "";
      const match = eligibleProviders.find((p) => p.id === providerId);
      return match?.name ?? providerId;
    },
    [eligibleProviders],
  );

  const resolveModelLabel = useCallback(
    (providerId?: string | null, modelId?: string | null) => {
      if (!providerId || !modelId) return "";
      const match = eligibleProviders.find((p) => p.id === providerId);
      const model = match?.models.find((m) => m.id === modelId);
      return model?.name || modelId;
    },
    [eligibleProviders],
  );

  const formatSlotSummary = useCallback(
    (slot: ModelSlotConfig | null) => {
      if (!slot) {
        return t("chatRoutingSelector.unconfigured", {
          defaultValue: "Unconfigured",
        });
      }
      return `${resolveProviderLabel(slot.provider_id)} · ${resolveModelLabel(
        slot.provider_id,
        slot.model,
      )}`;
    },
    [resolveModelLabel, resolveProviderLabel, t],
  );

  const activeModelName = useMemo(() => {
    if (routingEnabled) {
      return t("chatRoutingSelector.routing", { defaultValue: "Routing" });
    }
    if (!activeProviderId || !activeModelId) {
      return t("modelSelector.selectModel");
    }
    return resolveModelLabel(activeProviderId, activeModelId) || activeModelId;
  }, [activeModelId, activeProviderId, resolveModelLabel, routingEnabled, t]);

  const triggerBadge = routingEnabled
    ? routingMode === "cloud_first"
      ? "Cloud"
      : "Local"
    : null;

  const showActiveProviderIcon = Boolean(activeProviderId);

  const triggerTooltip = useMemo(() => {
    if (routingEnabled) {
      const modeLabel =
        routingMode === "cloud_first"
          ? t("chatRoutingSelector.cloudFirst", { defaultValue: "Cloud First" })
          : t("chatRoutingSelector.localFirst", {
              defaultValue: "Local First",
            });
      return (
        <div>
          <div>
            {t("chatRoutingSelector.routing", { defaultValue: "Routing" })}:{" "}
            {modeLabel}
          </div>
          <div>
            {t("chatRoutingSelector.local", { defaultValue: "Local" })}:{" "}
            {formatSlotSummary(effectiveLocalSlot)}
          </div>
          <div>
            {t("chatRoutingSelector.cloud", { defaultValue: "Cloud" })}:{" "}
            {formatSlotSummary(effectiveCloudSlot)}
          </div>
        </div>
      );
    }
    if (activeProviderId && activeModelId) {
      return `${resolveProviderLabel(activeProviderId)} · ${resolveModelLabel(
        activeProviderId,
        activeModelId,
      )}`;
    }
    return t("chat.modelSelectTooltip");
  }, [
    activeModelId,
    activeProviderId,
    effectiveCloudSlot,
    effectiveLocalSlot,
    formatSlotSummary,
    resolveModelLabel,
    resolveProviderLabel,
    routingEnabled,
    routingMode,
    t,
  ]);

  const runSavingAction = useCallback(
    async (action: () => Promise<void>, fallbackMessage: string) => {
      if (savingRef.current) return false;

      savingRef.current = true;
      setSaving(true);
      try {
        await action();
        return true;
      } catch (err) {
        message.error(err instanceof Error ? err.message : fallbackMessage);
        return false;
      } finally {
        setSaving(false);
        savingRef.current = false;
      }
    },
    [message],
  );

  const handleOpenChange = useCallback(
    async (next: boolean) => {
      setOpen(next);
      if (next) {
        await loadData(false);
      }
    },
    [loadData],
  );

  const handleSelectModel = async (providerId: string, modelId: string) => {
    if (
      !routingEnabled &&
      providerId === activeProviderId &&
      modelId === activeModelId
    ) {
      setOpen(false);
      return;
    }

    const targetProvider = eligibleProviders.find(
      (provider) => provider.id === providerId,
    );
    const targetModel = targetProvider?.models.find(
      (model) => model.id === modelId,
    );

    setOpen(false);

    if (targetProvider && targetModel) {
      const confirmed = await confirmFreeModelSwitch({
        provider: targetProvider,
        model: targetModel,
        t,
      });
      if (!confirmed) return;
    }

    await runSavingAction(async () => {
      await providerApi.setActiveLlm({
        provider_id: providerId,
        model: modelId,
        scope: "agent",
        agent_id: selectedAgent,
      });

      // Picking a concrete provider/model is an explicit single-model choice,
      // so disable routing to honor that intent until the user re-enables it.
      if (routingEnabled && routingConfig) {
        await providerApi.setRoutingConfig(
          {
            ...routingConfig,
            enabled: false,
          },
          {
            agent_id: selectedAgent,
          },
        );
      }

      await loadData(false);
      window.dispatchEvent(new CustomEvent("model-switched"));
    }, t("modelSelector.switchFailed"));
  };

  const buildRoutingBody = useCallback(
    (overrides: Partial<RoutingConfig>): RoutingConfig => {
      return {
        enabled: routingBase?.enabled ?? false,
        mode: routingBase?.mode ?? "local_first",
        local:
          getConfiguredSlot(routingBase?.local) ??
          effectiveLocalSlot ??
          EMPTY_LOCAL_SLOT,
        cloud:
          getConfiguredSlot(routingBase?.cloud) ?? effectiveCloudSlot ?? null,
        ...overrides,
      };
    },
    [effectiveCloudSlot, effectiveLocalSlot, routingBase],
  );

  const handleActivateRouting = async (mode: RoutingMode) => {
    if (!routingFeatureReady) {
      message.warning(
        t("chatRoutingSelector.configureSlotFirst", {
          defaultValue:
            "Configure both local and cloud slots in Settings > Models first.",
        }),
      );
      return;
    }
    if (routingEnabled && routingMode === mode) {
      setOpen(false);
      return;
    }

    const body = buildRoutingBody({ enabled: true, mode });

    const updated = await runSavingAction(
      async () => {
        await providerApi.setRoutingConfig(body, {
          agent_id: selectedAgent,
        });
        await loadData(false);
        window.dispatchEvent(new CustomEvent("model-switched"));
      },
      t("chatRoutingSelector.updateFailed", {
        defaultValue: "Failed to update routing mode.",
      }),
    );

    if (updated) {
      setOpen(false);
    }
  };

  const handleSetSlot = async (
    kind: SlotKind,
    providerId: string,
    modelId: string,
  ) => {
    const newSlot: ModelSlotConfig = {
      provider_id: providerId,
      model: modelId,
    };
    const currentSlot =
      kind === "local" ? effectiveLocalSlot : effectiveCloudSlot;
    if (
      currentSlot?.provider_id === providerId &&
      currentSlot?.model === modelId
    ) {
      return;
    }
    const body = buildRoutingBody(
      kind === "local" ? { local: newSlot } : { cloud: newSlot },
    );

    await runSavingAction(
      async () => {
        await providerApi.setRoutingConfig(body, {
          agent_id: selectedAgent,
        });
        await loadData(false);
        window.dispatchEvent(new CustomEvent("model-switched"));
      },
      t("chatRoutingSelector.updateFailed", {
        defaultValue: "Failed to update routing slot.",
      }),
    );
  };

  const renderProviderModelMenu = useCallback(
    (
      providersList: EligibleProvider[],
      selectedSlot: ModelSlotConfig | null,
      onSelect: (providerId: string, modelId: string) => void,
    ) =>
      providersList.map((provider) => {
        const isProviderActive = selectedSlot?.provider_id === provider.id;
        return (
          <div
            key={provider.id}
            className={[
              styles.providerItem,
              isProviderActive ? styles.providerItemActive : "",
            ].join(" ")}
          >
            <img
              src={providerIcon(provider.id)}
              alt=""
              className={styles.providerIcon}
            />
            <span className={styles.providerName}>{provider.name}</span>
            <RightOutlined className={styles.providerArrow} />
            <div className={`${styles.submenu} modelSubmenu`}>
              {provider.models.map((model) => {
                const isActive =
                  isProviderActive && selectedSlot?.model === model.id;
                return (
                  <div
                    key={model.id}
                    className={[
                      styles.modelItem,
                      isActive ? styles.modelItemActive : "",
                    ].join(" ")}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelect(provider.id, model.id);
                    }}
                  >
                    <span className={styles.modelName}>
                      {model.name || model.id}
                    </span>
                    {isActive && <CheckOutlined className={styles.checkIcon} />}
                  </div>
                );
              })}
            </div>
          </div>
        );
      }),
    [],
  );

  const dropdownContent = (
    <div className={styles.panel}>
      {loading ? (
        <div className={styles.spinWrapper}>
          <Spin size="small" />
        </div>
      ) : eligibleProviders.length === 0 ? (
        <div className={styles.emptyTip}>
          {t("modelSelector.noConfiguredModels")}
        </div>
      ) : (
        <>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>
              {t("chatRoutingSelector.availableModels", {
                defaultValue: "Available Models",
              })}
            </div>
            {renderProviderModelMenu(
              eligibleProviders,
              activeModelSlot,
              (providerId, modelId) => {
                void handleSelectModel(providerId, modelId);
              },
            )}
          </div>

          <div className={styles.sectionDivider} />

          <RoutingSection
            routingFeatureReady={routingFeatureReady}
            routingEnabled={routingEnabled}
            routingMode={routingMode}
            effectiveLocalSlot={effectiveLocalSlot}
            effectiveCloudSlot={effectiveCloudSlot}
            localProviders={localProviders}
            cloudProviders={cloudProviders}
            renderProviderModelMenu={renderProviderModelMenu}
            onActivateRouting={handleActivateRouting}
            onSetSlot={handleSetSlot}
          />
        </>
      )}
    </div>
  );

  return (
    <Dropdown
      open={open}
      onOpenChange={handleOpenChange}
      dropdownRender={() => dropdownContent}
      trigger={["click"]}
      placement="bottomLeft"
    >
      <Tooltip title={triggerTooltip} mouseEnterDelay={0.5}>
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
          {triggerBadge ? (
            <span className={styles.triggerBadge}>{triggerBadge}</span>
          ) : null}
          <SparkDownLine
            className={[
              styles.triggerArrow,
              open ? styles.triggerArrowOpen : "",
            ].join(" ")}
          />
        </div>
      </Tooltip>
    </Dropdown>
  );
}
