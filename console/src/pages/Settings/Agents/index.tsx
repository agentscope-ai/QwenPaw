import { useState } from "react";
import { Card, Button, Form, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import type { AgentSummary } from "../../../api/types/agents";
import { useAgents } from "./useAgents";
import { PageHeader, AgentTable, AgentModal } from "./components";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t } = useTranslation();
  const { agents, loading, deleteAgent, loadAgents } = useAgents();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [form] = Form.useForm();

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
      form.setFieldsValue(config);
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

      if (editingAgent) {
        await agentsApi.updateAgent(editingAgent.id, values);
        message.success(t("agent.updateSuccess"));
      } else {
        const result = await agentsApi.createAgent(values);
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
      }

      setModalVisible(false);
      await loadAgents();
    } catch (error: any) {
      console.error("Failed to save agent:", error);
      message.error(error.message || t("agent.saveFailed"));
    }
  };

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
        onSave={handleSubmit}
        onCancel={() => setModalVisible(false)}
      />
    </div>
  );
}
