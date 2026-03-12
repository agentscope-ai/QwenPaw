import { useState, useEffect, useCallback, useRef } from "react";
import { Dropdown, message, Spin } from "antd";
import {
  DownOutlined,
  CheckOutlined,
  LoadingOutlined,
  RightOutlined,
} from "@ant-design/icons";
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
  const savingRef = useRef(false);

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

  const handleSelect = async (providerId: string, modelId: string) => {
    if (savingRef.current) return;
    if (providerId === activeProviderId && modelId === activeModelId) {
      setOpen(false);
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setOpen(false);
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
      onOpenChange={setOpen}
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
