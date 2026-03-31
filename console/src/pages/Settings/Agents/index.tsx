import { useState, useRef } from "react";
import { Card, Button, Form } from "antd";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import { skillApi } from "../../../api/modules/skill";
import type { AgentSummary } from "../../../api/types/agents";
import { useAgents } from "./useAgents";
import { useAgentStore } from "../../../stores/agentStore";
import { AgentTable, AgentModal } from "./components";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t } = useTranslation();
  const { agents, loading, deleteAgent, toggleAgent, loadAgents } = useAgents();
  const { selectedAgent, setSelectedAgent } = useAgentStore();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [form] = Form.useForm();
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const installedSkillsRef = useRef<string[]>([]);
  const { message } = useAppMessage();

  const handleCreate = () => {
    setEditingAgent(null);
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
    });
    setSelectedSkills([]);
    installedSkillsRef.current = [];
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

      // If deleting the currently selected agent, fall back to default
      if (selectedAgent === agentId) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
    } catch {
      // Error already handled in hook
      message.error(t("agent.deleteFailed"));
    }
  };

  const handleToggle = async (agentId: string, currentEnabled: boolean) => {
    const newEnabled = !currentEnabled;
    try {
      await toggleAgent(agentId, newEnabled);

      // If disabling the current agent, switch to default
      if (!newEnabled && selectedAgent === agentId) {
        setSelectedAgent("default");
        message.info(t("agent.switchedToDefault"));
      }
    } catch {
      // Error already handled in hook
    }
  };

  const handleInstalledSkillsLoaded = (skills: string[]) => {
    installedSkillsRef.current = skills;
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      const workspaceRaw = values.workspace_dir;
      const workspace_dir =
        typeof workspaceRaw === "string"
          ? workspaceRaw.trim() || undefined
          : workspaceRaw;
      const payload = { ...values, workspace_dir };

      if (editingAgent) {
        const newSkills = selectedSkills.filter(
          (s) => !installedSkillsRef.current.includes(s),
        );
        for (const skill of newSkills) {
          await skillApi.downloadSkillPoolSkill({
            skill_name: skill,
            targets: [{ workspace_id: editingAgent.id }],
          });
        }
        await agentsApi.updateAgent(editingAgent.id, payload);
        message.success(t("agent.updateSuccess"));
      } else {
        const result = await agentsApi.createAgent({
          ...payload,
          skill_names: selectedSkills,
        });
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
        parent={t("agent.parent")}
        current={t("agent.agents")}
        extra={
          <div className={styles.headerRight}>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreate}
            >
              {t("agent.create")}
            </Button>
          </div>
        }
      />

      <Card className={styles.tableCard}>
        <AgentTable
          agents={agents}
          loading={loading}
          onEdit={handleEdit}
          onDelete={handleDelete}
          onToggle={handleToggle}
        />
      </Card>

      <AgentModal
        open={modalVisible}
        editingAgent={editingAgent}
        form={form}
        selectedSkills={selectedSkills}
        onSelectedSkillsChange={setSelectedSkills}
        onInstalledSkillsLoaded={handleInstalledSkillsLoaded}
        onSave={handleSubmit}
        onCancel={() => setModalVisible(false)}
      />
    </div>
  );
}
