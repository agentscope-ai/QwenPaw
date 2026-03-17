import { useState, useEffect } from "react";
import {
  Card,
  Table,
  Button,
  Space,
  Modal,
  Form,
  Input,
  message,
  Popconfirm,
} from "antd";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import type { AgentSummary } from "../../../api/types/agents";
import { useAgentStore } from "../../../stores/agentStore";
import styles from "./index.module.less";

export default function AgentsPage() {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [form] = Form.useForm();
  const { setAgents: updateStoreAgents } = useAgentStore();

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    setLoading(true);
    try {
      const data = await agentsApi.listAgents();
      setAgents(data.agents);
      updateStoreAgents(data.agents);
    } catch (error) {
      console.error("Failed to load agents:", error);
      message.error(t("agent.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

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
      await agentsApi.deleteAgent(agentId);
      message.success(t("agent.deleteSuccess"));
      loadAgents();
    } catch (error: any) {
      message.error(error.message || t("agent.deleteFailed"));
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
      loadAgents();
    } catch (error: any) {
      console.error("Failed to save agent:", error);
      message.error(error.message || t("agent.saveFailed"));
    }
  };

  const columns = [
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      render: (text: string) => (
        <Space>
          <RobotOutlined style={{ fontSize: 16 }} />
          <span>{text}</span>
        </Space>
      ),
    },
    {
      title: t("agent.id"),
      dataIndex: "id",
      key: "id",
    },
    {
      title: t("agent.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: t("agent.workspace"),
      dataIndex: "workspace_dir",
      key: "workspace_dir",
      ellipsis: true,
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 200,
      render: (_: any, record: AgentSummary) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
            disabled={record.id === "default"}
            title={
              record.id === "default"
                ? t("agent.defaultNotEditable")
                : undefined
            }
          >
            {t("common.edit")}
          </Button>
          <Popconfirm
            title={t("agent.deleteConfirm")}
            description={t("agent.deleteConfirmDesc")}
            onConfirm={() => handleDelete(record.id)}
            disabled={record.id === "default"}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={record.id === "default"}
              title={
                record.id === "default"
                  ? t("agent.defaultNotDeletable")
                  : undefined
              }
            >
              {t("common.delete")}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.agentsPage}>
      <Card
        title={
          <Space>
            <RobotOutlined />
            <span>{t("agent.management")}</span>
          </Space>
        }
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
            {t("agent.create")}
          </Button>
        }
      >
        <Table
          dataSource={agents}
          columns={columns}
          loading={loading}
          rowKey="id"
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showTotal: (total) => t("common.total", { count: total }),
          }}
        />
      </Card>

      <Modal
        title={
          editingAgent
            ? t("agent.editTitle", { name: editingAgent.name })
            : t("agent.createTitle")
        }
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={600}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
      >
        <Form form={form} layout="vertical" autoComplete="off">
          {editingAgent && (
            <Form.Item name="id" label={t("agent.id")}>
              <Input disabled />
            </Form.Item>
          )}
          <Form.Item
            name="name"
            label={t("agent.name")}
            rules={[{ required: true, message: t("agent.nameRequired") }]}
          >
            <Input placeholder={t("agent.namePlaceholder")} />
          </Form.Item>
          <Form.Item name="description" label={t("agent.description")}>
            <Input.TextArea
              placeholder={t("agent.descriptionPlaceholder")}
              rows={3}
            />
          </Form.Item>
          <Form.Item
            name="workspace_dir"
            label={t("agent.workspace")}
            help={t("agent.workspaceHelp")}
          >
            <Input placeholder="~/.copaw/workspaces/my-agent" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
