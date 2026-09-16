import { useTranslation } from "react-i18next";
import { Tag, Tooltip, Button, Select, Space, Switch, Typography } from "antd";
import { Package, Trash2, CheckCircle, XCircle } from "lucide-react";
import type { PluginType, PluginInfo } from "@/api/modules/plugin";
import type { AdminUser } from "@/api/modules/adminUsers";
import { PluginTypeTag } from "../components/PluginTypeTag";

const { Text } = Typography;

interface UsePluginColumnsOptions {
  uninstallingId: string | null;
  onUninstall: (record: PluginInfo) => void;
  onEnabledChange: (record: PluginInfo, enabled: boolean) => void;
  onAudienceChange: (
    record: PluginInfo,
    mode: "all_members" | "selected_users",
    selectedUserIds?: string[],
  ) => void;
  users: AdminUser[];
}

export function usePluginColumns({
  uninstallingId,
  onUninstall,
  onEnabledChange,
  onAudienceChange,
  users,
}: UsePluginColumnsOptions) {
  const { t } = useTranslation();

  return [
    {
      title: t("pluginManager.title"),
      dataIndex: "name",
      key: "name",
      render: (name: string, record: PluginInfo) => (
        <Space direction="vertical" size={2}>
          <Space size={8}>
            <Package size={16} style={{ flexShrink: 0 }} />
            <Text strong>{name}</Text>
          </Space>
          {record.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: t("pluginManager.type"),
      dataIndex: "plugin_type",
      key: "plugin_type",
      width: 110,
      render: (type: PluginType) => <PluginTypeTag type={type ?? "general"} />,
    },
    {
      title: t("pluginManager.version"),
      dataIndex: "version",
      key: "version",
      width: 100,
      render: (version: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {version}
        </Text>
      ),
    },
    {
      title: t("pluginManager.author"),
      dataIndex: "author",
      key: "author",
      width: 140,
      render: (author: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {author || t("pluginManager.unknown")}
        </Text>
      ),
    },
    {
      title: "授权范围",
      key: "audience",
      width: 280,
      render: (_: unknown, record: PluginInfo) => (
        <Space direction="vertical" size={4} style={{ width: "100%" }}>
          <Select
            size="small"
            value={record.audience_mode ?? "selected_users"}
            onChange={(value) => onAudienceChange(record, value)}
            options={[
              { value: "all_members", label: "全体成员" },
              { value: "selected_users", label: "指定用户" },
            ]}
          />
          {(record.audience_mode ?? "selected_users") === "selected_users" && (
            <>
              <Select
                aria-label="指定授权用户"
                mode="multiple"
                size="small"
                style={{ width: "100%" }}
                placeholder="选择可使用此应用的用户"
                value={record.selected_user_ids ?? []}
                onChange={(ids) =>
                  onAudienceChange(record, "selected_users", ids)
                }
                options={users
                  .filter((user) => user.status === "active")
                  .map((user) => ({ value: user.id, label: user.username }))}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                已授权 {record.selected_user_ids?.length ?? 0} 位用户
              </Text>
            </>
          )}
        </Space>
      ),
    },
    {
      title: "Status",
      dataIndex: "loaded",
      key: "loaded",
      width: 110,
      render: (loaded: boolean, record: PluginInfo) => (
        <Space>
          <Switch
            size="small"
            checked={
              (record.status ?? (record.enabled ? "active" : "disabled")) ===
              "active"
            }
            onChange={(checked) => onEnabledChange(record, checked)}
          />
          {loaded ? (
            <Tag
              icon={<CheckCircle size={12} />}
              color="success"
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              {t("pluginManager.statusLoaded")}
            </Tag>
          ) : (
            <Tag
              icon={<XCircle size={12} />}
              color="default"
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              {t("pluginManager.statusUnloaded")}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: unknown, record: PluginInfo) => (
        <Tooltip title={t("pluginManager.uninstall")}>
          <Button
            type="text"
            danger
            size="small"
            icon={<Trash2 size={14} />}
            loading={uninstallingId === record.id}
            onClick={() => onUninstall(record)}
          />
        </Tooltip>
      ),
    },
  ];
}
