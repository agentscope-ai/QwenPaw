import { useState, useEffect } from "react";
import { Card, Button, Form, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import { providerApi } from "../../../api/modules/provider";
import type { AgentSummary, ModelSlotConfig } from "../../../api/types/agents";
import type { ProviderInfo } from "../../../api/types/provider";
import { useAgents } from "./useAgents";
import { PageHeader, AgentTable, AgentModal } from "./components";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t } = useTranslation();
  const { agents, loading, deleteAgent } = useAgents();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [form] = Form.useForm();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [defaultModel, setDefaultModel] = useState<
    ModelSlotConfig | undefined
  >();

  // Load providers and default model on mount
  useEffect(() => {
    const loadData = async () => {
      try {
        const [providersData, activeModels] = await Promise.all([
          providerApi.listProviders(),
          providerApi.getActiveModels(),
        ]);
        setProviders(providersData);
        setDefaultModel(activeModels.active_llm || undefined);
      } catch (error) {
        console.error("Failed to load providers:", error);
      }
    };
    loadData();
  }, []);

  const handleCreate = () => {
    setEditingAgent(null);
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
    });
    setModalVisible(true);
  };

  const handleEdit = async (agent: AgentSummary) => {
    try {
      const config = await agentsApi.getAgent(agent.id);
      setEditingAgent(agent);
      form.setFieldsValue({
        ...config,
        active_model: config.active_model || {
          provider_id: undefined,
          model: undefined,
        },
        orchestration: {
          can_spawn_agents: config.orchestration?.can_spawn_agents ?? false,
          allowed_agents: config.orchestration?.allowed_agents ?? [],
          max_spawn_depth: config.orchestration?.max_spawn_depth ?? 3,
        },
      });
      setModalVisible(true);
    } catch (error) {
      console.error("Failed to load agent config:", error);
      message.error(t("agent.loadConfigFailed"));
    }
  };

  const handleDelete = async (agentId: string) => {
    try {
      await deleteAgent(agentId);
    } catch {
      // Error already handled in hook
      message.error(t("agent.deleteFailed"));
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      // Clean up active_model if empty
      if (!values.active_model?.provider_id || !values.active_model?.model) {
        values.active_model = undefined;
      }

      if (editingAgent) {
        await agentsApi.updateAgent(editingAgent.id, values);
        message.success(t("agent.updateSuccess"));
      } else {
        const result = await agentsApi.createAgent(values);
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
      }

      setModalVisible(false);
    } catch (error: any) {
      console.error("Failed to save agent:", error);
      message.error(error.message || t("agent.saveFailed"));
    }
  };

  const agentsList = agents.map((agent) => ({
    value: agent.id,
    label: agent.name || agent.id,
  }));

  return (
    <div className={styles.agentsPage}>
      <PageHeader
        title={t("agent.management")}
        description={t("agent.pageDescription")}
        action={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
            {t("agent.create")}
          </Button>
        }
      />

      <Card className={styles.tableCard}>
        <AgentTable
          agents={agents}
          loading={loading}
          onEdit={handleEdit}
          onDelete={handleDelete}
        />
      </Card>

      <AgentModal
        open={modalVisible}
        editingAgent={editingAgent}
        form={form}
        agentsList={agentsList}
        providers={providers}
        defaultModel={defaultModel}
        onSave={handleSubmit}
        onCancel={() => setModalVisible(false)}
      />
    </div>
  );
}
