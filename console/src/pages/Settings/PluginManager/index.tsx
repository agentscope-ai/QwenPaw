import { useTranslation } from "react-i18next";
import { Button, Empty, Spin, Table, Tabs, Tag } from "antd";
import { ExternalLink, Package, Plus, Trash2, CheckCircle, XCircle } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { usePluginManager } from "./hooks/usePluginManager";
import { usePluginColumns } from "./hooks/usePluginColumns";
import { useInstallModal } from "./hooks/useInstallModal";
import { InstallPluginModal } from "./components/InstallPluginModal";
import { OfficialPluginList } from "./components/OfficialPluginList";
import { MarketPluginList } from "./components/MarketPluginList";
import styles from "./index.module.less";
import type { PluginInfo } from "@/api/modules/plugin";
import { PluginTypeTag } from "./components/PluginTypeTag";

function PluginCard({
  plugin,
  uninstallingId,
  onUninstall,
  t,
}: {
  plugin: PluginInfo;
  uninstallingId: string | null;
  onUninstall: (record: PluginInfo) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  return (
    <div className={styles.pluginCard}>
      <div className={styles.pluginCardHeader}>
        <div className={styles.pluginCardTitle}>
          <Package size={18} />
          <span>{plugin.name}</span>
        </div>
        <Tag
          icon={
            plugin.loaded ? (
              <CheckCircle size={12} />
            ) : (
              <XCircle size={12} />
            )
          }
          color={plugin.loaded ? "success" : "default"}
          className={styles.pluginCardStatus}
        >
          {plugin.loaded
            ? t("pluginManager.statusLoaded")
            : t("pluginManager.statusUnloaded")}
        </Tag>
      </div>

      {plugin.description && (
        <div className={styles.pluginCardDesc}>{plugin.description}</div>
      )}

      <div className={styles.pluginCardMeta}>
        <div className={styles.pluginCardMetaItem}>
          <span className={styles.pluginCardMetaLabel}>类型</span>
          <PluginTypeTag type={plugin.plugin_type || "general"} />
        </div>
        <div className={styles.pluginCardMetaItem}>
          <span className={styles.pluginCardMetaLabel}>版本</span>
          <span>{plugin.version || "-"}</span>
        </div>
        <div className={styles.pluginCardMetaItem}>
          <span className={styles.pluginCardMetaLabel}>作者</span>
          <span>{plugin.author || t("pluginManager.unknown")}</span>
        </div>
      </div>

      <div className={styles.pluginCardActions}>
        <Button
          type="text"
          danger
          size="small"
          icon={<Trash2 size={14} />}
          loading={uninstallingId === plugin.id}
          onClick={() => onUninstall(plugin)}
        >
          {t("pluginManager.uninstall")}
        </Button>
      </div>
    </div>
  );
}

export default function PluginManagerPage() {
  const { t } = useTranslation();

  const { plugins, loading, refresh, uninstallingId, handleUninstall } =
    usePluginManager();

  const installModal = useInstallModal(refresh);

  const columns = usePluginColumns({
    uninstallingId,
    onUninstall: handleUninstall,
  });

  const tabItems = [
    {
      key: "installed",
      label: t("pluginManager.installed"),
      children: (
        <Spin spinning={loading}>
          {!loading && (!plugins || plugins.length === 0) ? (
            <Empty
              image={<Package size={48} strokeWidth={1} />}
              description={t("pluginManager.noPlugins")}
              style={{ marginTop: 24 }}
            />
          ) : (
            <div className={styles.desktopTable}>
              <Table
                dataSource={plugins}
                columns={columns}
                rowKey="id"
                pagination={false}
                className={styles.table}
              />
            </div>
          )}
          {!loading && plugins && plugins.length > 0 && (
            <div className={styles.mobileCards}>
              {plugins.map((plugin) => (
                <PluginCard
                  key={plugin.id}
                  plugin={plugin}
                  uninstallingId={uninstallingId}
                  onUninstall={handleUninstall}
                  t={t}
                />
              ))}
            </div>
          )}
        </Spin>
      ),
    },
    {
      key: "official",
      label: t("pluginManager.officialTitle"),
      children: <OfficialPluginList onInstalled={refresh} />,
    },
    {
      key: "market",
      label: t("pluginManager.marketTitle"),
      children: <MarketPluginList onInstalled={refresh} />,
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.pluginManager")}
        extra={
          <>
            <Button
              icon={<ExternalLink size={16} />}
              onClick={() =>
                window.open("https://platform.agentscope.io/plugins", "_blank")
              }
            >
              {t("pluginManager.publishBtn")}
            </Button>
            <Button
              type="primary"
              icon={<Plus size={16} />}
              onClick={installModal.openModal}
            >
              {t("pluginManager.installBtn")}
            </Button>
          </>
        }
      />

      <div className={styles.content}>
        <Tabs items={tabItems} className={styles.tabs} />
      </div>

      <InstallPluginModal {...installModal} />
    </div>
  );
}
