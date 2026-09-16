import { Button, Popconfirm, Space, Table, Tag } from "antd";
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
          render: (_value, agent: AdminAgentSummary) => {
            const published = agent.visibility === "public";
            return (
              <Space>
                <Button onClick={() => onEdit(agent)}>
                  {t("agent.governanceEdit")}
                </Button>
                <Button onClick={() => onRuntimeConfig(agent)}>
                  {t("agent.governanceRuntimeConfig")}
                </Button>
                <Button onClick={() => onMemoryFiles(agent)}>
                  {t("agent.governanceMemoryFiles")}
                </Button>
                <Popconfirm
                  title={t(
                    published
                      ? "agent.revokePublicationConfirm"
                      : "agent.publishConfirm",
                  )}
                  onConfirm={() => onPublication(agent, !published)}
                >
                  <Button danger={published}>
                    {t(
                      published
                        ? "agent.revokePublication"
                        : "agent.publishPublic",
                    )}
                  </Button>
                </Popconfirm>
              </Space>
            );
          },
        },
      ]}
    />
  );
}
