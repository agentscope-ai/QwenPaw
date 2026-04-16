import { useState } from "react";
import { Button, Card, Table } from "@agentscope-ai/design";
import { Space } from "antd";
import { useTranslation } from "react-i18next";
import type { TablePaginationConfig } from "antd";
import type {
  AgentSACPConfig,
  CreateAgentSACPRequest,
  UpdateAgentSACPRequest,
} from "@/api/types/agent_sacp";
import { createColumns } from "./components/AgentSACPTable";
import { AgentSACPModal } from "./components/AgentSACPModal";
import { GlobalAuthKeyModal } from "./components/GlobalAuthKeyModal";
import { useAgentSACP } from "./useAgentSACP";
import styles from "./index.module.less";

function AgentSACPPage() {
  const { t } = useTranslation();
  const {
    agents,
    internalAgents,
    globalAuthKey,
    loading,
    channelEnabledMap,
    createAgent,
    updateAgent,
    deleteAgent,
    healthCheckAgent,
    toggleChannel,
    updateGlobalAuthKey,
  } = useAgentSACP();
  const [modalVisible, setModalVisible] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<AgentSACPConfig | null>(
    null,
  );
  const [saving, setSaving] = useState(false);
  const [globalAuthKeyModalVisible, setGlobalAuthKeyModalVisible] =
    useState(false);
  const [globalAuthKeySaving, setGlobalAuthKeySaving] = useState(false);

  const handleCreate = () => {
    setSelectedAgent(null);
    setModalVisible(true);
  };

  const handleEdit = (record: AgentSACPConfig) => {
    setSelectedAgent(record);
    setModalVisible(true);
  };

  const handleDelete = (agentId: string) => {
    deleteAgent(agentId);
  };

  const handleHealthCheck = (record: AgentSACPConfig) => {
    healthCheckAgent(record.id);
  };

  const handleToggleChannel = (agentId: string, enabled: boolean) => {
    toggleChannel(agentId, enabled);
  };

  const handleBulkHealthCheck = () => {
    agents.forEach((agent) => {
      healthCheckAgent(agent.id);
    });
  };

  const handleOpenGlobalAuthKey = () => {
    setGlobalAuthKeyModalVisible(true);
  };

  const handleSaveGlobalAuthKey = async (value: string) => {
    setGlobalAuthKeySaving(true);
    try {
      await updateGlobalAuthKey(value);
      setGlobalAuthKeyModalVisible(false);
    } finally {
      setGlobalAuthKeySaving(false);
    }
  };

  const handleModalClose = () => {
    setModalVisible(false);
    setSelectedAgent(null);
  };

  const handleModalSubmit = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      let success = false;
      if (selectedAgent) {
        const updateData: UpdateAgentSACPRequest = {
          name: values.name as string | null,
          description: values.description as string | null,
          url: values.url as string | null,
          auth_key: values.auth_key as string | null,
          is_internal: values.is_internal as boolean | null,
          internal_agent_id: values.internal_agent_id as string | null,
          health_check_enabled: values.health_check_enabled as boolean | null,
          health_check_interval: values.health_check_interval as number | null,
        };
        success = await updateAgent(selectedAgent.id, updateData);
      } else {
        const createData: CreateAgentSACPRequest = {
          name: values.name as string,
          description: values.description as string | undefined,
          url: values.url as string,
          auth_key: values.auth_key as string,
          is_internal: values.is_internal as boolean | undefined,
          internal_agent_id: values.internal_agent_id as string | null,
          health_check_enabled: values.health_check_enabled as
            | boolean
            | undefined,
          health_check_interval: values.health_check_interval as
            | number
            | undefined,
        };
        success = await createAgent(createData);
      }
      if (success) {
        setModalVisible(false);
      }
    } finally {
      setSaving(false);
    }
  };

  const columns = createColumns(
    {
      onEdit: handleEdit,
      onDelete: handleDelete,
      onHealthCheck: handleHealthCheck,
      onToggleChannel: handleToggleChannel,
      channelEnabledMap,
      t,
    },
    t,
  );

  const pagination: TablePaginationConfig = {
    pageSize: 10,
    showSizeChanger: false,
    showTotal: (total: number) => t("agentSACP.totalItems", { count: total }),
  };

  return (
    <div className={styles.sacpAgentsPage}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <h1 className={styles.title}>{t("agentSACP.title")}</h1>
          <p className={styles.description}>{t("agentSACP.description")}</p>
        </div>
        <div className={styles.headerActions}>
          <Space size={8}>
            <Button onClick={handleBulkHealthCheck}>
              {t("agentSACP.bulkHealthCheck")}
            </Button>
            <Button onClick={handleOpenGlobalAuthKey}>
              {t("agentSACP.globalAuthKey")}
            </Button>
            <Button type="primary" onClick={handleCreate}>
              + {t("agentSACP.createAgent")}
            </Button>
          </Space>
        </div>
      </div>

      <Card className={styles.tableCard} bodyStyle={{ padding: 0 }}>
        <Table
          columns={columns}
          dataSource={agents}
          loading={loading}
          rowKey="id"
          pagination={pagination}
        />
      </Card>

      <AgentSACPModal
        open={modalVisible}
        editingAgent={selectedAgent}
        saving={saving}
        internalAgents={internalAgents}
        globalAuthKey={globalAuthKey}
        onClose={handleModalClose}
        onSubmit={handleModalSubmit}
      />

      <GlobalAuthKeyModal
        open={globalAuthKeyModalVisible}
        initialValue={globalAuthKey}
        saving={globalAuthKeySaving}
        onClose={() => setGlobalAuthKeyModalVisible(false)}
        onSave={handleSaveGlobalAuthKey}
      />
    </div>
  );
}

export default AgentSACPPage;
