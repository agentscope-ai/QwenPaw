import { useCallback, useEffect, useState } from "react";
import { Button, Select, Space, Tooltip } from "antd";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  modelCatalogApi,
  type CatalogModel,
  type ConversationModel,
} from "@/api/modules/modelCatalog";
import { useAgentStore } from "@/stores/agentStore";
import { useAuthStore } from "@/stores/authStore";
import {
  chooseConversationModel,
  currentModelContext,
  isCurrentModelContext,
  loadConversationModel,
  resetConversationModelScope,
} from "../conversationModel";
import { useTurnUsageStore } from "../turnUsageStore";

export default function ModelSelector() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const userId = useAuthStore((state) => state.user?.id);
  const location = useLocation();
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [active, setActive] = useState<ConversationModel>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => resetConversationModelScope(), []);
  const refresh = useCallback(async () => {
    const context = currentModelContext(location.pathname);
    setLoading(true);
    setError("");
    try {
      const catalog = await modelCatalogApi.list(selectedAgent);
      if (!isCurrentModelContext(context)) return;
      setModels(catalog.models);
      const result = await loadConversationModel();
      if (!isCurrentModelContext(context)) return;
      setActive(result);
      useTurnUsageStore
        .getState()
        .setActiveMaxInputLength(result.effective_max_input_length ?? null);
    } catch (error) {
      if (isCurrentModelContext(context)) {
        setActive(undefined);
        setError(error instanceof Error ? error.message : "模型不可用");
      }
    } finally {
      if (isCurrentModelContext(context)) setLoading(false);
    }
  }, [selectedAgent, userId, location.pathname]);
  useEffect(() => {
    setActive(undefined);
    setModels([]);
    void refresh();
    const update = () => void refresh();
    window.addEventListener("model-switched", update);
    return () => window.removeEventListener("model-switched", update);
  }, [refresh]);
  const selected = models.find(
    (m) =>
      m.provider_id === active?.active_llm?.provider_id &&
      m.model === active?.active_llm?.model,
  );
  const select = async (id?: string) => {
    const context = currentModelContext();
    const row = models.find((m) => m.id === id);
    setLoading(true);
    try {
      const result = await chooseConversationModel(
        row ? { provider_id: row.provider_id, model: row.model } : null,
      );
      if (isCurrentModelContext(context)) setActive(result);
    } catch (error) {
      if (isCurrentModelContext(context))
        setError(error instanceof Error ? error.message : "切换失败");
    } finally {
      if (isCurrentModelContext(context)) setLoading(false);
    }
  };
  return (
    <Tooltip
      title={
        error ||
        `${t("modelSelector.conversationHint")} · ${t(
          "modelSelector.contextWindow",
          { tokens: active?.effective_max_input_length ?? "—" },
        )}`
      }
    >
      <Space size={4}>
        <Select
          aria-label={t("modelSelector.conversationModel")}
          showSearch
          optionFilterProp="label"
          style={{ minWidth: 160, maxWidth: 320 }}
          loading={loading}
          disabled={active?.locked}
          value={selected?.id}
          placeholder={error || t("modelSelector.selectModel")}
          onChange={(id) => void select(id)}
          options={models.map((m) => ({
            value: m.id,
            label: `${m.provider_name} / ${m.name}`,
            title: `${m.max_input_length} tokens${
              m.supports_image ? " · Image" : ""
            }${m.supports_video ? " · Video" : ""}`,
          }))}
        />
        <Button
          size="small"
          disabled={active?.locked || loading}
          onClick={() => void select()}
        >
          {t("modelSelector.resetConversation")}
        </Button>
      </Space>
    </Tooltip>
  );
}
