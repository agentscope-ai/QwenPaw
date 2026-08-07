import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Popover, Select, Spin } from "antd";
import { Brain, Check, ChevronDown, Cpu } from "lucide-react";
import { useTranslation } from "react-i18next";

import { agentsApi } from "@/api/modules/agents";
import { harnessApi, type HarnessModel } from "@/api/modules/harness";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAgentStore } from "@/stores/agentStore";
import styles from "./HarnessModelSelector.module.less";

interface HarnessModelSelectorProps {
  providerId: string;
}

interface HarnessModelCatalog {
  providerId: string;
  models: HarnessModel[];
}

export default function HarnessModelSelector({
  providerId,
}: HarnessModelSelectorProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent, agents, updateAgent } = useAgentStore();
  const agent = agents.find((item) => item.id === selectedAgent);
  const [catalog, setCatalog] = useState<HarnessModelCatalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const autoSelectingRef = useRef<string | null>(null);
  const models = useMemo(
    () => (catalog?.providerId === providerId ? catalog.models : []),
    [catalog, providerId],
  );
  const modelId = agent?.backend_model ?? undefined;
  const model = useMemo(
    () => models.find((item) => item.id === modelId),
    [modelId, models],
  );
  const effort = agent?.backend_reasoning_effort ?? undefined;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    harnessApi
      .listModels(providerId)
      .then((result) => {
        if (!cancelled) {
          setCatalog({ providerId, models: result.models });
          if (result.message) {
            message.warning(result.message);
          }
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setCatalog({ providerId, models: [] });
          message.error(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [message, providerId]);

  const save = useCallback(
    async (nextModel?: HarnessModel, nextEffort?: string) => {
      setSaving(true);
      try {
        await agentsApi.updateBackendSettings(selectedAgent, {
          model: nextModel?.id,
          reasoning_effort: nextEffort,
        });
        updateAgent(selectedAgent, {
          backend_model: nextModel?.id ?? null,
          backend_reasoning_effort: nextEffort ?? null,
        });
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error));
      } finally {
        setSaving(false);
      }
    },
    [message, selectedAgent, updateAgent],
  );

  useEffect(() => {
    if (!agent || modelId || loading || models.length === 0) return;
    const selectionKey = `${selectedAgent}:${providerId}`;
    if (autoSelectingRef.current === selectionKey) return;
    const defaultModel = models.find((item) => item.is_default) ?? models[0];
    autoSelectingRef.current = selectionKey;
    void save(defaultModel, defaultModel.default_reasoning_effort ?? undefined);
  }, [agent, loading, modelId, models, providerId, save, selectedAgent]);

  const selectedLabel =
    model?.name ??
    models.find((item) => item.is_default)?.name ??
    t("agent.backend.modelDefault");

  const content = (
    <div className={styles.panel}>
      <div className={styles.heading}>
        <span>{providerId}</span>
        <small>{t("agent.backend.chatModelHint")}</small>
      </div>
      <label>
        <span>
          <Cpu size={14} />
          {t("agent.backend.model")}
        </span>
        <Select
          value={modelId}
          allowClear
          showSearch
          loading={loading}
          optionFilterProp="label"
          placeholder={t("agent.backend.modelDefault")}
          options={models.map((item) => ({
            value: item.id,
            label: item.name,
          }))}
          onChange={(value) => {
            const next = models.find((item) => item.id === value);
            void save(next, next?.default_reasoning_effort ?? undefined);
          }}
        />
      </label>
      <label>
        <span>
          <Brain size={14} />
          {t("agent.backend.reasoningEffort")}
        </span>
        <Select
          value={effort}
          allowClear
          disabled={!model?.reasoning_efforts.length}
          placeholder={t("agent.backend.reasoningDefault")}
          options={(model?.reasoning_efforts ?? []).map((item) => ({
            value: item,
            label: item,
          }))}
          onChange={(value) => void save(model, value)}
        />
      </label>
      <div className={styles.footer}>
        {saving ? <Spin size="small" /> : <Check size={13} />}
        {saving ? t("common.saving") : t("agent.backend.appliesNextTurn")}
      </div>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
      overlayClassName={styles.overlay}
    >
      <button type="button" className={styles.trigger}>
        <Cpu size={15} />
        <span>{loading ? t("common.loading") : selectedLabel}</span>
        <ChevronDown size={14} />
      </button>
    </Popover>
  );
}
