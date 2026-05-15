import { useTranslation } from "react-i18next";
import {
  Button,
  Tag,
  Tooltip,
  Empty,
  Spin,
  Typography,
  Space,
  Table,
} from "antd";
import { Package, Plus, Trash2, CheckCircle, XCircle } from "lucide-react";
import type { PluginType, PluginInfo } from "@/api/modules/plugin";
import { PageHeader } from "@/components/PageHeader";
import { usePluginManager } from "./hooks/usePluginManager";
import { useInstallModal } from "./hooks/useInstallModal";
import { InstallPluginModal } from "./components/InstallPluginModal";
import { PluginTypeTag } from "./components/PluginTypeTag";
import styles from "./index.module.less";

const { Text } = Typography;

export default function PluginManagerPage() {
  const { t } = useTranslation();

  const { plugins, loading, refresh, uninstallingId, handleUninstall } =
    usePluginManager();

  const installModal = useInstallModal(refresh);

  const columns = [
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
      render: (v: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {v}
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
      width: 100,
      render: (_: unknown, record: PluginInfo) => (
        <Tooltip title={t("pluginManager.uninstall")}>
          <Button
            type="text"
            danger
            size="small"
            icon={<Trash2 size={14} />}
            loading={uninstallingId === record.id}
            onClick={() => handleUninstall(record)}
          />
        </Tooltip>
      ),
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.pluginManager")}
        extra={
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={installModal.openModal}
          >
            {t("pluginManager.installBtn")}
          </Button>
        }
      />

      <div className={styles.content}>
        <Spin spinning={loading}>
          {!loading && (!plugins || plugins.length === 0) ? (
            <Empty
              image={<Package size={48} strokeWidth={1} />}
              description={t("pluginManager.noPlugins")}
              style={{ marginTop: 80 }}
            />
          ) : (
            <Table
              dataSource={plugins}
              columns={columns}
              rowKey="id"
              pagination={false}
              className={styles.table}
            />
          )}
        </Spin>
      </div>

      <InstallPluginModal {...installModal} />
    </div>
  );
}
