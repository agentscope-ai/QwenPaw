import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Empty, Spin } from "antd";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "@/hooks/useAppMessage";
import { Slot } from "@/plugins/registry/Slot";
import {
  installPlugin,
  type OfficialPluginCatalogEntry,
} from "@/api/modules/plugin";
import { CreatorDiscoveryList } from "./components/CreatorDiscoveryList";
import { useCreatorApps } from "./hooks/useCreatorApps";
import styles from "./index.module.less";

export default function CreatorPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { apps, loading, error, refresh } = useCreatorApps();
  const [installingId, setInstallingId] = useState<string | null>(null);

  const handleInstall = useCallback(
    async (entry: OfficialPluginCatalogEntry) => {
      setInstallingId(entry.id);
      try {
        await installPlugin(entry.install_url, { force: true });
        message.success(t("creator.installSuccess", { name: entry.name }));
        window.location.reload();
      } catch (err) {
        message.error(
          err instanceof Error ? err.message : t("creator.installFailed"),
        );
        setInstallingId(null);
      }
    },
    [message, t],
  );

  const defaultContent = (
    <div className={styles.content}>
      <PageHeader current={t("nav.creator", { defaultValue: "Creator" })} />
      {error && (
        <Alert
          type="warning"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={refresh}>
              {t("creator.retry")}
            </Button>
          }
          style={{ marginBottom: 16 }}
        />
      )}
      <Spin spinning={loading}>
        {!loading && apps.length === 0 && !error && (
          <Empty
            description={t("creator.empty")}
            style={{ marginTop: "30%" }}
          />
        )}
        {apps.length > 0 && (
          <CreatorDiscoveryList
            apps={apps}
            installingId={installingId}
            onInstall={handleInstall}
          />
        )}
      </Spin>
    </div>
  );

  return (
    <div className={styles.page}>
      <Slot name="creator.content" kind="replace">
        {defaultContent}
      </Slot>
    </div>
  );
}
