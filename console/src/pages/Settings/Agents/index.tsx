import { useRef, useState } from "react";
import { Card, Button, Form, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi, buildAgentAvatarUrl } from "../../../api/modules/agents";
import type {
  AgentProfileConfig,
  AgentSummary,
} from "../../../api/types/agents";
import { useAgents } from "./useAgents";
import { PageHeader, AgentTable, AgentModal } from "./components";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t } = useTranslation();
  const { agents, loading, deleteAgent, loadAgents } = useAgents();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentProfileConfig | null>(
    null,
  );
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState<string>();
  const [avatarMarkedForRemoval, setAvatarMarkedForRemoval] = useState(false);
  const [form] = Form.useForm();
  const avatarObjectUrlRef = useRef<string | null>(null);

  const clearAvatarObjectUrl = () => {
    if (avatarObjectUrlRef.current) {
      URL.revokeObjectURL(avatarObjectUrlRef.current);
      avatarObjectUrlRef.current = null;
    }
  };

  const resetAvatarState = () => {
    clearAvatarObjectUrl();
    setAvatarFile(null);
    setAvatarPreviewUrl(undefined);
    setAvatarMarkedForRemoval(false);
  };

  const handleCreate = () => {
    setEditingAgent(null);
    resetAvatarState();
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
    });
    setModalVisible(true);
  };

  const handleEdit = async (agent: AgentSummary) => {
    try {
      const config = await agentsApi.getAgent(agent.id);
      resetAvatarState();
      setEditingAgent(config);
      setAvatarPreviewUrl(
        buildAgentAvatarUrl(config.id, config.avatar, Date.now()),
      );
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

  const handleAvatarChange = (file: File) => {
    clearAvatarObjectUrl();
    const objectUrl = URL.createObjectURL(file);
    avatarObjectUrlRef.current = objectUrl;
    setAvatarFile(file);
    setAvatarPreviewUrl(objectUrl);
    setAvatarMarkedForRemoval(false);
  };

  const handleAvatarRemove = () => {
    clearAvatarObjectUrl();
    setAvatarFile(null);
    setAvatarPreviewUrl(undefined);
    setAvatarMarkedForRemoval(true);
  };

  const closeModal = () => {
    setModalVisible(false);
    setEditingAgent(null);
    resetAvatarState();
    form.resetFields();
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (editingAgent) {
        const mergedConfig: AgentProfileConfig = {
          ...editingAgent,
          ...values,
        };

        await agentsApi.updateAgent(editingAgent.id, mergedConfig);
        if (avatarMarkedForRemoval) {
          await agentsApi.deleteAvatar(editingAgent.id);
        } else if (avatarFile) {
          await agentsApi.uploadAvatar(editingAgent.id, avatarFile);
        }
        message.success(t("agent.updateSuccess"));
      } else {
        const result = await agentsApi.createAgent(values);
        if (avatarFile) {
          await agentsApi.uploadAvatar(result.id, avatarFile);
        }
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
      }

      await loadAgents();
      closeModal();
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
        avatarPreviewUrl={avatarPreviewUrl}
        onAvatarChange={handleAvatarChange}
        onAvatarRemove={handleAvatarRemove}
        onSave={handleSubmit}
        onCancel={closeModal}
      />
    </div>
  );
}
