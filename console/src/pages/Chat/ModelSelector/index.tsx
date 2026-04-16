import { useState, useEffect, useCallback, useRef } from "react";
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
import type { ProviderInfo, ActiveModelsInfo } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning.tsx";
import { providerIcon } from "../../Settings/Models/components/providerIcon";
import styles from "./index.module.less";

interface EligibleProvider {
  id: string;
  name: string;
  base_url?: string;
  models: Array<{ id: string; name: string; is_free?: boolean }>;
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
  const savingRef = useRef(false);
  const location = useLocation();
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();

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

  // Eligible providers: configured + has models
  const eligibleProviders: EligibleProvider[] = providers
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
      models: [...(p.models ?? []), ...(p.extra_models ?? [])],
    }));

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

  const activeProviderIconUrl = activeProviderId
    ? providerIcon(activeProviderId)
    : null;

  const handleOpenChange = useCallback(
    async (next: boolean) => {
      setOpen(next);
      if (next) {
        // Re-fetch active model every time the dropdown opens
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
      // Notify ChatPage to refresh multimodal capabilities
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
        eligibleProviders.map((provider) => {
          const isProviderActive = provider.id === activeProviderId;
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

              {/* Level-2 submenu — shown on parent hover via CSS */}
              <div className={`${styles.submenu} modelSubmenu`}>
                {provider.models.map((model) => {
                  const isActive =
                    isProviderActive && model.id === activeModelId;
                  return (
                    <div
                      key={model.id}
                      className={[
                        styles.modelItem,
                        isActive ? styles.modelItemActive : "",
                      ].join(" ")}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSelect(provider.id, model.id);
                      }}
                    >
                      <span className={styles.modelName}>
                        {model.name || model.id}
                      </span>
                      {isActive && (
                        <CheckOutlined className={styles.checkIcon} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
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
      <Tooltip title={t("chat.modelSelectTooltip")} mouseEnterDelay={0.5}>
        <div
          className={[styles.trigger, open ? styles.triggerActive : ""].join(
            " ",
          )}
        >
          {saving && (
            <LoadingOutlined style={{ fontSize: 11, color: "#FF7F16" }} />
          )}
          {activeProviderIconUrl && (
            <img
              src={activeProviderIconUrl}
              alt=""
              className={styles.providerIcon}
            />
          )}
          <span className={styles.triggerName}>{activeModelName}</span>
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
