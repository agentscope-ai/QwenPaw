import type { ColumnsType } from "antd/es/table";
import { Tag, Button, Space, Popconfirm, Switch } from "antd";
import {
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  CopyOutlined,
} from "@ant-design/icons";
import { Check } from "lucide-react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import type { AgentSACPConfig } from "@/api/types/agent_sacp";
import type { TFunction } from "i18next";
import { useState } from "react";

dayjs.extend(relativeTime);

interface AgentSACPHandlers {
  onEdit: (agent: AgentSACPConfig) => void;
  onDelete: (agentId: string) => void;
  onHealthCheck: (agent: AgentSACPConfig) => void;
  onToggleChannel: (agentId: string, enabled: boolean) => void;
  channelEnabledMap: Record<string, boolean>;
  t: TFunction;
}

export const createColumns = (
  handlers: AgentSACPHandlers,
  t: TFunction,
): ColumnsType<AgentSACPConfig> => [
  {
    title: t("agentSACP.columns.name"),
    dataIndex: "name",
    key: "name",
    width: 200,
    fixed: "left",
  },
  {
    title: t("agentSACP.columns.type"),
    dataIndex: "is_internal",
    key: "is_internal",
    width: 120,
    render: (_: unknown, record: AgentSACPConfig) => (
      <Tag color={record.is_internal ? "blue" : "green"}>
        {record.is_internal
          ? t("agentSACP.type.internal")
          : t("agentSACP.type.external")}
      </Tag>
    ),
  },
  {
    title: t("agentSACP.columns.sacpChannel"),
    key: "sacp_channel",
    width: 120,
    render: (_: unknown, record: AgentSACPConfig) => {
      if (!record.is_internal) {
        return <span style={{ color: "#999" }}>—</span>;
      }
      return (
        <Switch
          checked={handlers.channelEnabledMap[record.id] ?? false}
          onChange={(checked) => handlers.onToggleChannel(record.id, checked)}
          checkedChildren="ON"
          unCheckedChildren="OFF"
        />
      );
    },
  },
  {
    title: t("agentSACP.columns.status"),
    dataIndex: "health_status",
    key: "health_status",
    width: 120,
    render: (_: unknown, record: AgentSACPConfig) => {
      const statusConfig: Record<string, { color: string; label: string }> = {
        healthy: { color: "success", label: t("agentSACP.status.healthy") },
        unhealthy: { color: "error", label: t("agentSACP.status.unhealthy") },
        unknown: { color: "warning", label: t("agentSACP.status.unknown") },
      };
      const config = statusConfig[record.health_status] || statusConfig.unknown;
      return <Tag color={config.color}>{config.label}</Tag>;
    },
  },
  {
    title: t("agentSACP.columns.lastCheck"),
    dataIndex: "last_health_check",
    key: "last_health_check",
    width: 160,
    render: (_: unknown, record: AgentSACPConfig) => {
      if (!record.last_health_check) return "—";
      return dayjs(record.last_health_check).fromNow();
    },
  },
  {
    title: t("agentSACP.columns.lastError"),
    dataIndex: "last_health_error",
    key: "last_health_error",
    width: 220,
    ellipsis: true,
    render: (_: unknown, record: AgentSACPConfig) => {
      if (!record.last_health_error) return "—";
      return (
        <Space size="small">
          <span
            style={{
              maxWidth: 150,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {record.last_health_error}
          </span>
          <CopyButton text={record.last_health_error} />
        </Space>
      );
    },
  },
  {
    title: t("agentSACP.columns.actions"),
    key: "actions",
    width: 140,
    fixed: "right",
    render: (_: unknown, record: AgentSACPConfig) => (
      <Space size="small">
        <Button
          type="text"
          size="small"
          icon={<EditOutlined />}
          onClick={() => handlers.onEdit(record)}
        />
        <Button
          type="text"
          size="small"
          icon={<CheckCircleOutlined />}
          onClick={() => handlers.onHealthCheck(record)}
        />
        <Popconfirm
          title={t("agentSACP.deleteConfirm")}
          onConfirm={() => handlers.onDelete(record.id)}
          okText={t("common.confirm")}
          cancelText={t("common.cancel")}
        >
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      </Space>
    ),
  },
];

// Copy button component
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Button
      type="text"
      size="small"
      icon={copied ? <Check size={12} /> : <CopyOutlined />}
      onClick={handleCopy}
    />
  );
}
