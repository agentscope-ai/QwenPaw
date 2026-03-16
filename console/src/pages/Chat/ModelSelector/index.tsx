import { useState, useEffect, useCallback, useRef } from "react";
import { Dropdown, message, Spin } from "antd";
import {
  DownOutlined,
  CheckOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { useLocation } from "react-router-dom";
import { providerApi } from "../../../api/modules/provider";
import type { ProviderInfo, ActiveModelsInfo } from "../../../api/types";
import styles from "./index.module.less";

interface EligibleProvider {
  id: string;
  name: string;
  models: Array<{ id: string; name: string }>;
}

export default function ModelSelector() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const savingRef = useRef(false);
  const location = useLocation();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [provData, activeData] = await Promise.all([
        providerApi.listProviders(),
        providerApi.getActiveModels(),
      ]);
      if (Array.isArray(provData)) setProviders(provData);
      if (activeData) setActiveModels(activeData);
    } catch (err) {
      console.error("ModelSelector: failed to load data", err);
    } finally {
      setLoading(false);
    }
  }, []);

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
        .getActiveModels()
        .then((activeData) => {
          if (activeData) setActiveModels(activeData);
        })
        .catch(() => {});
    }
  }, [location.pathname]);

  // Eligible providers: configured + has models
  const eligibleProviders: EligibleProvider[] = providers
    .filter((p) => {
      const hasModels =
        (p.models?.length ?? 0) + (p.extra_models?.length ?? 0) > 0;
      if (!hasModels) return false;
      if (p.is_local) return true;
      if (p.id === "ollama") return !!p.base_url;
      if (p.is_custom) return !!p.base_url;
      return !!p.api_key;
    })
    .map((p) => ({
      id: p.id,
      name: p.name,
      models: [...(p.models ?? []), ...(p.extra_models ?? [])],
    }));

  const activeProviderId = activeModels?.active_llm?.provider_id;
  const activeModelId = activeModels?.active_llm?.model;

  // Display label for trigger button
  const activeModelName = (() => {
    if (!activeProviderId || !activeModelId) return "Select model";
    for (const p of eligibleProviders) {
      if (p.id === activeProviderId) {
        const m = p.models.find((m) => m.id === activeModelId);
        if (m) return m.name || m.id;
      }
    }
    return activeModelId;
  })();

  const handleOpenChange = useCallback(async (next: boolean) => {
    setOpen(next);
    if (next) {
      try {
        const activeData = await providerApi.getActiveModels();
        if (activeData) setActiveModels(activeData);
      } catch {
        // ignore
      }
    } else {
      setExpandedProvider(null);
    }
  }, []);

  const handleSelect = async (providerId: string, modelId: string) => {
    if (savingRef.current) return;
    if (providerId === activeProviderId && modelId === activeModelId) {
      setOpen(false);
      setExpandedProvider(null);
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setOpen(false);
    setExpandedProvider(null);
    try {
      await providerApi.setActiveLlm({
        provider_id: providerId,
        model: modelId,
      });
      setActiveModels({
        active_llm: { provider_id: providerId, model: modelId },
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to switch model";
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
        <div className={styles.emptyTip}>No configured models</div>
      ) : (
        eligibleProviders.map((provider) => {
          const isProviderActive = provider.id === activeProviderId;
          const isExpanded = expandedProvider === provider.id;
          return (
            <div key={provider.id}>
              <div
                className={[
                  styles.providerItem,
                  isProviderActive && styles.providerItemActive,
                  isExpanded && styles.providerItemExpanded,
                ]
                  .filter(Boolean)
                  .join(" ")}
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded ? "true" : "false"}
                onClick={() =>
                  setExpandedProvider(isExpanded ? null : provider.id)
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setExpandedProvider(isExpanded ? null : provider.id);
                  }
                }}
              >
                <span className={styles.providerName}>{provider.name}</span>
                <DownOutlined
                  className={[
                    styles.providerArrow,
                    isExpanded ? styles.providerArrowOpen : "",
                  ].join(" ")}
                />
              </div>
              {isExpanded && (
                <div className={styles.submenu}>
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
              )}
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
      <div
        className={[styles.trigger, open ? styles.triggerActive : ""].join(" ")}
      >
        {saving && (
          <LoadingOutlined style={{ fontSize: 11, color: "#615ced" }} />
        )}
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
