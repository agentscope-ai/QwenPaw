import { EditOutlined, GlobalOutlined } from "@ant-design/icons";
import { Brain, SlidersHorizontal } from "lucide-react";
import { Button, Popconfirm, Space, Table, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import type { AdminAgentSummary } from "@/api/types/agents";

interface AdminAgentsTableProps {
  agents: AdminAgentSummary[];
  loading: boolean;
  onEdit: (agent: AdminAgentSummary) => void;
  onMemoryFiles: (agent: AdminAgentSummary) => void;
  onRuntimeConfig: (agent: AdminAgentSummary) => void;
  onPublication: (agent: AdminAgentSummary, published: boolean) => void;
}

export function AdminAgentsTable({
  agents,
  loading,
  onEdit,
  onMemoryFiles,
  onRuntimeConfig,
  onPublication,
}: AdminAgentsTableProps) {
  const { t } = useTranslation();
  return (
    <Table
      rowKey="id"
      loading={loading}
      dataSource={agents}
      pagination={false}
      columns={[
        { title: t("agent.name"), dataIndex: "name" },
        { title: t("agent.id"), dataIndex: "id" },
        {
          title: t("agent.owner"),
          dataIndex: "owner_user_id",
          ellipsis: true,
        },
        {
          title: t("agent.visibility.column"),
          dataIndex: "visibility",
          render: (visibility: AdminAgentSummary["visibility"]) => (
            <Tag color={visibility === "public" ? "blue" : undefined}>
              {t(`agent.visibility.${visibility}`)}
            </Tag>
          ),
        },
        {
          title: t("common.actions"),
          width: 220,
          fixed: "right",
          render: (_value, agent: AdminAgentSummary) => {
            const published = agent.visibility === "public";
            return (
              <Space>
                <Tooltip title={t("agent.governanceEdit")}>
                  <Button
                    type="text"
                    size="middle"
                    aria-label={t("agent.governanceEdit")}
                    icon={<EditOutlined />}
                    onClick={() => onEdit(agent)}
                  />
                </Tooltip>
                <Tooltip title={t("agent.governanceRuntimeConfig")}>
                  <Button
                    type="text"
                    size="middle"
                    aria-label={t("agent.governanceRuntimeConfig")}
                    icon={<SlidersHorizontal size={15} />}
                    onClick={() => onRuntimeConfig(agent)}
                  />
                </Tooltip>
                <Tooltip title={t("agent.governanceMemoryFiles")}>
                  <Button
                    type="text"
                    size="middle"
                    aria-label={t("agent.governanceMemoryFiles")}
                    icon={<Brain size={15} />}
                    onClick={() => onMemoryFiles(agent)}
                  />
                </Tooltip>
                <Popconfirm
                  title={t(
                    published
                      ? "agent.revokePublicationConfirm"
                      : "agent.publishConfirm",
                  )}
                  onConfirm={() => onPublication(agent, !published)}
                >
                  <Tooltip
                    title={t(
                      published
                        ? "agent.revokePublication"
                        : "agent.publishPublic",
                    )}
                  >
                    <Button
                      type="text"
                      size="middle"
                      danger={published}
                      aria-label={t(
                        published
                          ? "agent.revokePublication"
                          : "agent.publishPublic",
                      )}
                      icon={<GlobalOutlined />}
                    />
                  </Tooltip>
                </Popconfirm>
              </Space>
            );
          },
        },
      ]}
    />
  );
}
