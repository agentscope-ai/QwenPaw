import { useTranslation } from "react-i18next";
import { Button, Tabs } from "antd";
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

  const { plugins, loading, refresh, uninstallingId, handleUninstall } =
    usePluginManager();

  const installModal = useInstallModal(refresh);

  const tabItems = [
    {
      key: "installed",
      label: t("pluginManager.installed"),
      children: (
        <InstalledPluginList
          plugins={plugins}
          loading={loading}
          uninstallingId={uninstallingId}
          onRefresh={refresh}
          onUninstall={handleUninstall}
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
      children: <MarketPluginList onInstalled={refresh} />,
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
        <Tabs items={tabItems} className={styles.tabs} />
      </div>

      <InstallPluginModal {...installModal} />
    </div>
  );
}
