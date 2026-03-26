import { Table, Button, Space, Popconfirm, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import { EditOutlined, DeleteOutlined, RobotOutlined } from "@ant-design/icons";
import { EyeOff, Eye } from "lucide-react";
import type { AgentSummary } from "../../../../api/types/agents";
import { useTheme } from "../../../../contexts/ThemeContext";
import styles from "../index.module.less";

interface AgentTableProps {
  agents: AgentSummary[];
  loading: boolean;
  onEdit: (agent: AgentSummary) => void;
  onDelete: (agentId: string) => void;
  onToggle: (agentId: string, currentEnabled: boolean) => void;
}

export function AgentTable({
  agents,
  loading,
  onEdit,
  onDelete,
  onToggle,
}: AgentTableProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();

  // Inline style for disabled buttons — CSS cannot reliably override AntD's disabled styles
  const disabledStyle: React.CSSProperties = isDark
    ? { color: "rgba(255,255,255,0.35)", opacity: 1 }
    : {};

  const columns: ColumnsType<AgentSummary> = [
    {
      title: t("agent.name"),
      dataIndex: "name",
      key: "name",
      render: (text: string, record: AgentSummary) => (
        <Space>
          <RobotOutlined
            style={{
              fontSize: 16,
              opacity: record.enabled ? 1 : 0.5,
            }}
          />
          <span style={{ opacity: record.enabled ? 1 : 0.5 }}>{text}</span>
          {!record.enabled && <Tag color="error">{t("agent.disabled")}</Tag>}
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
      width: 400,
      render: (_: any, record: AgentSummary) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record)}
            disabled={record.id === "default"}
            style={record.id === "default" ? disabledStyle : undefined}
            title={
              record.id === "default"
                ? t("agent.defaultNotEditable")
                : undefined
            }
          >
            {t("common.edit")}
          </Button>
          <Popconfirm
            title={
              record.enabled
                ? t("agent.disableConfirm")
                : t("agent.enableConfirm")
            }
            description={
              record.enabled
                ? t("agent.disableConfirmDesc")
                : t("agent.enableConfirmDesc")
            }
            onConfirm={() => onToggle(record.id, record.enabled)}
            disabled={record.id === "default"}
            okText={t("common.confirm")}
            cancelText={t("common.cancel")}
          >
            <Button
              type="link"
              size="small"
              icon={record.enabled ? <EyeOff size={14} /> : <Eye size={14} />}
              disabled={record.id === "default"}
              style={record.id === "default" ? disabledStyle : undefined}
              title={
                record.id === "default"
                  ? t("agent.defaultNotDisablable")
                  : undefined
              }
            >
              {record.enabled ? t("agent.disable") : t("agent.enable")}
            </Button>
          </Popconfirm>
          <Popconfirm
            title={t("agent.deleteConfirm")}
            description={t("agent.deleteConfirmDesc")}
            onConfirm={() => onDelete(record.id)}
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
              style={record.id === "default" ? disabledStyle : undefined}
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
    <div className={styles.tableCard}>
      <Table
        dataSource={agents}
        columns={columns}
        loading={loading}
        rowKey="id"
        pagination={{
          pageSize: 10,
          showSizeChanger: false,
        }}
      />
    </div>
  );
}
