import { useTranslation } from "react-i18next";
import { Badge, Button, Tabs } from "antd";
import { useSearchParams } from "react-router-dom";
import { ExternalLink, Plus } from "lucide-react";
import { MarketplaceHeader } from "@/pages/Market/components/MarketplaceHeader";
import { usePluginManager } from "./hooks/usePluginManager";
import { useInstallModal } from "./hooks/useInstallModal";
import { InstallPluginModal } from "./components/InstallPluginModal";
import { InstalledPluginList } from "./components/InstalledPluginList";
import { OfficialPluginList } from "./components/OfficialPluginList";
import { MarketPluginList } from "./components/MarketPluginList";
import styles from "./index.module.less";

export default function PluginManagerPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const activeTab =
    viewParam === "official" || viewParam === "market"
      ? viewParam
      : "installed";

  const {
    plugins,
    loading,
    refresh,
    uninstallingId,
    handleUninstall,
    updates,
    updatesLoading,
    updatingId,
    updatingAll,
    updateOne,
    updateAll,
  } = usePluginManager();

  const installModal = useInstallModal(refresh);

  const tabItems = [
    {
      key: "installed",
      label: (
        <span>
          {t("pluginManager.installed")}
          {updates.size > 0 && (
            <Badge count={updates.size} style={{ marginLeft: 8 }} />
          )}
        </span>
      ),
      children: (
        <InstalledPluginList
          plugins={plugins}
          loading={loading}
          uninstallingId={uninstallingId}
          onRefresh={refresh}
          onUninstall={handleUninstall}
          updates={updates}
          updatesLoading={updatesLoading}
          updatingId={updatingId}
          updatingAll={updatingAll}
          onUpdate={updateOne}
          onUpdateAll={updateAll}
        />
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
      children: (
        <MarketPluginList
          onInstalled={refresh}
          installedPlugins={plugins ?? []}
        />
      ),
    },
  ];

  return (
    <div className={styles.page}>
      <MarketplaceHeader
        activeSection="plugins"
        extra={
          <div className={styles.headerActions}>
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
          </div>
        }
      />

      <div className={styles.content}>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => {
            const next = new URLSearchParams(searchParams);
            if (key === "installed") next.delete("view");
            else next.set("view", key);
            setSearchParams(next, { replace: true });
          }}
          items={tabItems}
          className={styles.tabs}
        />
      </div>

      <InstallPluginModal {...installModal} />
    </div>
  );
}
