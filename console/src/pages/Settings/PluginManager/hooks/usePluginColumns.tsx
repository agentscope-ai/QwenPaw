import { useTranslation } from "react-i18next";
import { Tag, Tooltip, Button, Space, Typography } from "antd";
import { Package, Trash2, CheckCircle, XCircle, Download } from "lucide-react";
import type { PluginType, PluginInfo } from "@/api/modules/plugin";
import { PluginTypeTag } from "../components/PluginTypeTag";

const { Text } = Typography;

interface UsePluginColumnsOptions {
  uninstallingId: string | null;
  exportingId: string | null;
  onUninstall: (record: PluginInfo) => void;
  onExport: (record: PluginInfo) => void;
}

export function usePluginColumns({
  uninstallingId,
  exportingId,
  onUninstall,
  onExport,
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
      title: "Status",
      dataIndex: "loaded",
      key: "loaded",
      width: 110,
      render: (loaded: boolean) =>
        loaded ? (
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
        ),
    },
    {
      title: "",
      key: "actions",
      width: 130,
      render: (_: unknown, record: PluginInfo) => (
        <Space size={4}>
          <Tooltip title={t("pluginManager.export")}>
            <Button
              type="text"
              size="small"
              icon={<Download size={14} />}
              loading={exportingId === record.id}
              onClick={() => onExport(record)}
            />
          </Tooltip>
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
        </Space>
      ),
    },
  ];
}
