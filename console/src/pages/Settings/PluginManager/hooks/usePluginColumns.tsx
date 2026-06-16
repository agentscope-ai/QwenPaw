import { useTranslation } from "react-i18next";
import { Tag, Tooltip, Button, Space, Typography } from "antd";
import {
  Package,
  Trash2,
  CheckCircle,
  XCircle,
  Wrench,
} from "lucide-react";
import type { PluginType, PluginInfo } from "@/api/modules/plugin";
import { PluginTypeTag } from "../components/PluginTypeTag";

const { Text } = Typography;

interface UsePluginColumnsOptions {
  uninstallingId: string | null;
  repairingId: string | null;
  onUninstall: (record: PluginInfo) => void;
  onRepair: (record: PluginInfo) => void;
}

export function usePluginColumns({
  uninstallingId,
  repairingId,
  onUninstall,
  onRepair,
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
      title: t("pluginManager.status"),
      dataIndex: "load_status",
      key: "loaded",
      width: 150,
      render: (_: unknown, record: PluginInfo) => {
        const status =
          record.load_status ?? (record.loaded ? "loaded" : "unloaded");
        if (status === "needs_repair") {
          return (
            <Tooltip title={t("pluginManager.repairHint")}>
              <Tag
                icon={<Wrench size={12} />}
                color="warning"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                {t("pluginManager.statusNeedsRepair")}
              </Tag>
            </Tooltip>
          );
        }
        return record.loaded ? (
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
        );
      },
    },
    {
      title: "",
      key: "actions",
      width: 120,
      render: (_: unknown, record: PluginInfo) => (
        <Space size={4}>
          {record.repairable && record.load_status === "needs_repair" && (
            <Tooltip title={t("pluginManager.repair")}>
              <Button
                type="text"
                size="small"
                icon={<Wrench size={14} />}
                loading={repairingId === record.id}
                onClick={() => onRepair(record)}
              />
            </Tooltip>
          )}
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
