import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Dropdown, message, Spin } from "antd";
import {
  ApartmentOutlined,
  CheckOutlined,
  DownOutlined,
  LoadingOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import type {
  ProviderInfo,
  ActiveModelsInfo,
  LLMRoutingConfig,
  LLMRoutingMode,
  ModelSlotConfig,
} from "../../../api/types";
import styles from "./index.module.less";

interface EligibleProvider {
  id: string;
  name: string;
  is_local: boolean;
  models: Array<{ id: string; name: string }>;
}

function hasConfiguredSlot(
  slot?: ModelSlotConfig | null,
): slot is ModelSlotConfig {
  return Boolean(slot?.provider_id && slot?.model);
}

function encodeSlot(slot: ModelSlotConfig): string {
  return `${encodeURIComponent(slot.provider_id)}:${encodeURIComponent(
    slot.model,
  )}`;
}

function emptySlot(): ModelSlotConfig {
  return { provider_id: "", model: "" };
}

export default function ModelSelector() {
  const { t } = useTranslation();
  const location = useLocation();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [routingConfig, setRoutingConfig] = useState<LLMRoutingConfig | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const savingRef = useRef(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [provData, activeData, routingData] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels(),
        providerApi.getLlmRoutingConfig(),
      ]);
      if (Array.isArray(provData)) setProviders(provData);
      if (activeData) setActiveModels(activeData);
      if (routingData) setRoutingConfig(routingData);
    } catch (err) {
      console.error("ModelSelector: failed to load data", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    const prev = prevPathRef.current;
    const curr = location.pathname;
    prevPathRef.current = curr;
    const comingToChat = curr.startsWith("/chat") && !prev.startsWith("/chat");
    if (!comingToChat) return;
    providerApi
      .getActiveModels()
      .then((activeData) => {
        if (activeData) setActiveModels(activeData);
      })
      .catch(() => {});
    providerApi
      .getLlmRoutingConfig()
      .then((nextRouting) => {
        if (nextRouting) setRoutingConfig(nextRouting);
      })
      .catch(() => {});
  }, [location.pathname]);

  const eligibleProviders: EligibleProvider[] = useMemo(
    () =>
      providers
        .filter((p) => {
          const hasModels =
            (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
          if (!hasModels) return false;
          if (p.is_local) return true;
          if (p.require_api_key === false) return !!p.base_url;
          if (p.is_custom) return !!p.base_url;
          if (p.require_api_key ?? true) return !!p.api_key;
          return true;
        })
        .map((p) => ({
          id: p.id,
          name: p.name,
          is_local: p.is_local,
          models: [...(p.models ?? []), ...(p.extra_models ?? [])],
        })),
    [providers],
  );

  const activeProviderId = activeModels?.active_llm?.provider_id;
  const activeModelId = activeModels?.active_llm?.model;

  const localOptions = useMemo(
    () =>
      eligibleProviders
        .filter((p) => p.is_local)
        .flatMap((p) =>
          p.models.map((m) => ({
            key: encodeSlot({ provider_id: p.id, model: m.id }),
            label: `${p.name} / ${m.name || m.id}`,
            slot: { provider_id: p.id, model: m.id },
          })),
        ),
    [eligibleProviders],
  );

  const cloudOptions = useMemo(
    () =>
      eligibleProviders
        .filter((p) => !p.is_local)
        .flatMap((p) =>
          p.models.map((m) => ({
            key: encodeSlot({ provider_id: p.id, model: m.id }),
            label: `${p.name} / ${m.name || m.id}`,
            slot: { provider_id: p.id, model: m.id },
          })),
        ),
    [eligibleProviders],
  );

  const effectiveLocalSlot =
    routingConfig?.local && hasConfiguredSlot(routingConfig.local)
      ? routingConfig.local
      : localOptions[0]?.slot ?? null;

  const effectiveCloudSlot =
    routingConfig?.cloud && hasConfiguredSlot(routingConfig.cloud)
      ? routingConfig.cloud
      : cloudOptions[0]?.slot ?? null;

  const activeModelName = (() => {
    if (routingConfig?.enabled) return t("chatModelSelector.triggerRouting");
    if (!activeProviderId || !activeModelId) {
      return t("modelSelector.selectModel");
    }
    for (const p of eligibleProviders) {
      if (p.id === activeProviderId) {
        const m = p.models.find((model) => model.id === activeModelId);
        if (m) return m.name || m.id;
      }
    }
    return activeModelId;
  })();

  const handleOpenChange = useCallback(async (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) return;
    try {
      const [activeData, nextRouting] = await Promise.all([
        providerApi.getActiveModels(),
        providerApi.getLlmRoutingConfig(),
      ]);
      if (activeData) setActiveModels(activeData);
      if (nextRouting) setRoutingConfig(nextRouting);
    } catch {
      // ignore refresh errors when opening the dropdown
    }
  }, []);

  const handleSelectModel = async (providerId: string, modelId: string) => {
    if (savingRef.current) return;
    if (
      !routingConfig?.enabled &&
      providerId === activeProviderId &&
      modelId === activeModelId
    ) {
      setOpen(false);
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setOpen(false);
    try {
      const requests: Array<Promise<unknown>> = [
        providerApi.setActiveLlm({
          provider_id: providerId,
          model: modelId,
        }),
      ];
      if (routingConfig?.enabled) {
        requests.push(
          providerApi.setLlmRoutingConfig({
            ...routingConfig,
            enabled: false,
          }),
        );
      }
      await Promise.all(requests);
      setActiveModels({
        active_llm: { provider_id: providerId, model: modelId },
      });
      if (routingConfig?.enabled) {
        setRoutingConfig({ ...routingConfig, enabled: false });
      }
      message.success(
        routingConfig?.enabled
          ? t("chatModelSelector.routingDisabled")
          : t("models.llmModelUpdated"),
      );
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : t("chatModelSelector.updateFailed");
      message.error(msg);
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  const handleSelectRoutingMode = async (mode: LLMRoutingMode) => {
    if (savingRef.current) return;
    if (
      !hasConfiguredSlot(effectiveLocalSlot) ||
      !hasConfiguredSlot(effectiveCloudSlot)
    ) {
      message.warning(t("chatModelSelector.configureRoutingFirst"));
      return;
    }
    savingRef.current = true;
    setSaving(true);
    try {
      const nextRouting: LLMRoutingConfig = {
        enabled: true,
        mode,
        local: effectiveLocalSlot,
        cloud: effectiveCloudSlot,
      };
      await providerApi.setLlmRoutingConfig(nextRouting);
      setRoutingConfig(nextRouting);
      message.success(
        t(
          mode === "cloud_first"
            ? "chatModelSelector.routingCloudFirstEnabled"
            : "chatModelSelector.routingLocalFirstEnabled",
        ),
      );
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : t("chatModelSelector.updateFailed");
      message.error(msg);
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  const handleSelectRoutingSlot = async (
    kind: "local" | "cloud",
    slot: ModelSlotConfig,
  ) => {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const nextLocal =
        kind === "local"
          ? slot
          : effectiveLocalSlot ?? routingConfig?.local ?? emptySlot();
      const nextCloud =
        kind === "cloud"
          ? slot
          : effectiveCloudSlot ?? routingConfig?.cloud ?? null;

      const nextRouting: LLMRoutingConfig = {
        enabled: routingConfig?.enabled ?? false,
        mode: routingConfig?.mode ?? "local_first",
        local: nextLocal,
        cloud: nextCloud,
      };
      await providerApi.setLlmRoutingConfig(nextRouting);
      setRoutingConfig(nextRouting);
      message.success(t("chatModelSelector.routingModelUpdated"));
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : t("chatModelSelector.updateFailed");
      message.error(msg);
    } finally {
      setSaving(false);
      savingRef.current = false;
    }
  };

  const renderModelProviders = eligibleProviders.map((provider) => {
    const isProviderActive =
      !routingConfig?.enabled && provider.id === activeProviderId;
    return (
      <div
        key={provider.id}
        className={[
          styles.providerItem,
          isProviderActive ? styles.providerItemActive : "",
        ].join(" ")}
      >
        <span className={styles.providerName}>{provider.name}</span>
        <RightOutlined className={styles.providerArrow} />
        <div className={`${styles.submenu} modelSubmenu`}>
          {provider.models.map((model) => {
            const isActive =
              !routingConfig?.enabled &&
              isProviderActive &&
              model.id === activeModelId;
            return (
              <div
                key={model.id}
                className={[
                  styles.modelItem,
                  isActive ? styles.modelItemActive : "",
                ].join(" ")}
                onClick={(e) => {
                  e.stopPropagation();
                  void handleSelectModel(provider.id, model.id);
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
  });

  const renderRoutingSlot = (
    label: string,
    options: Array<{ key: string; label: string; slot: ModelSlotConfig }>,
    selectedKey: string,
    kind: "local" | "cloud",
  ) => {
    if (options.length <= 1) return null;
    return (
      <div className={styles.providerItem}>
        <span className={styles.providerName}>{label}</span>
        <RightOutlined className={styles.providerArrow} />
        <div className={`${styles.submenu} modelSubmenu`}>
          {options.map((option) => (
            <div
              key={option.key}
              className={[
                styles.modelItem,
                selectedKey === option.key ? styles.modelItemActive : "",
              ].join(" ")}
              onClick={(e) => {
                e.stopPropagation();
                void handleSelectRoutingSlot(kind, option.slot);
              }}
            >
              <span className={styles.modelName}>{option.label}</span>
              {selectedKey === option.key && (
                <CheckOutlined className={styles.checkIcon} />
              )}
            </div>
          ))}
        </div>
      </div>
    );
  };

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
          {renderModelProviders}
          <div className={styles.sectionDivider} />
          <div className={styles.sectionTitle}>
            {t("chatModelSelector.routingGroup")}
          </div>
          <div
            className={[
              styles.modelItem,
              routingConfig?.enabled && routingConfig.mode === "local_first"
                ? styles.modelItemActive
                : "",
            ].join(" ")}
            onClick={(e) => {
              e.stopPropagation();
              void handleSelectRoutingMode("local_first");
            }}
          >
            <span className={styles.modelName}>
              {t("chatModelSelector.localFirst")}
            </span>
            {routingConfig?.enabled && routingConfig.mode === "local_first" && (
              <CheckOutlined className={styles.checkIcon} />
            )}
          </div>
          <div
            className={[
              styles.modelItem,
              routingConfig?.enabled && routingConfig.mode === "cloud_first"
                ? styles.modelItemActive
                : "",
            ].join(" ")}
            onClick={(e) => {
              e.stopPropagation();
              void handleSelectRoutingMode("cloud_first");
            }}
          >
            <span className={styles.modelName}>
              {t("chatModelSelector.cloudFirst")}
            </span>
            {routingConfig?.enabled && routingConfig.mode === "cloud_first" && (
              <CheckOutlined className={styles.checkIcon} />
            )}
          </div>
          {renderRoutingSlot(
            t("chatModelSelector.localModel"),
            localOptions,
            hasConfiguredSlot(effectiveLocalSlot)
              ? encodeSlot(effectiveLocalSlot)
              : "",
            "local",
          )}
          {renderRoutingSlot(
            t("chatModelSelector.cloudModel"),
            cloudOptions,
            hasConfiguredSlot(effectiveCloudSlot)
              ? encodeSlot(effectiveCloudSlot)
              : "",
            "cloud",
          )}
        </>
      )}
    </div>
  );

  return (
    <Dropdown
      menu={{ selectable: true, multiple: true }}
      open={open}
      onOpenChange={handleOpenChange}
      dropdownRender={() => dropdownContent}
      trigger={["click"]}
      placement="bottomLeft"
    >
      <div
        className={[styles.trigger, open ? styles.triggerActive : ""].join(" ")}
      >
        {saving && (
          <LoadingOutlined style={{ fontSize: 11, color: "#615ced" }} />
        )}
        <ApartmentOutlined className={styles.triggerIcon} />
        <span className={styles.triggerName}>{activeModelName}</span>
        <DownOutlined
          className={[
            styles.triggerArrow,
            open ? styles.triggerArrowOpen : "",
          ].join(" ")}
        />
      </div>
    </Dropdown>
  );
}
