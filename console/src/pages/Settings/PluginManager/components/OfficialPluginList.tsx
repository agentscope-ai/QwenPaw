import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Space, Spin, Typography, Alert, Tag } from "antd";
import { Download, RefreshCw } from "lucide-react";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchPluginCatalog,
  installPlugin,
  type OfficialPluginCatalogEntry,
} from "@/api/modules/plugin";
import styles from "../index.module.less";

const { Text } = Typography;

interface OfficialPluginListProps {
  onInstalled: () => void;
}

export function OfficialPluginList({ onInstalled }: OfficialPluginListProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<OfficialPluginCatalogEntry[]>([]);
  const [installingId, setInstallingId] = useState<string | null>(null);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setCatalogError(null);
    try {
      const data = await fetchPluginCatalog();
      if (data.error) {
        setCatalogError(data.error);
        setPlugins([]);
      } else {
        setPlugins(data.plugins ?? []);
      }
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : t("pluginManager.catalogLoadFailed");
      setCatalogError(msg);
      setPlugins([]);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const handleInstall = useCallback(
    async (entry: OfficialPluginCatalogEntry) => {
      setInstallingId(entry.id);
      try {
        const result = await installPlugin(entry.install_url, {
          force: entry.installed || entry.upgrade_available,
        });
        message.success(`${t("pluginManager.installSuccess")}: ${result.name}`);
        onInstalled();
        await loadCatalog();
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : t("pluginManager.installFailed");
        message.error(msg);
      } finally {
        setInstallingId(null);
      }
    },
    [loadCatalog, message, onInstalled, t],
  );

  return (
    <div className={styles.catalogSection}>
      <div className={styles.catalogHeader}>
        <div>
          <Text strong>{t("pluginManager.officialTitle")}</Text>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("pluginManager.officialDesc")}
            </Text>
          </div>
        </div>
        <Button
          type="text"
          size="small"
          icon={<RefreshCw size={14} />}
          onClick={() => void loadCatalog()}
          disabled={loading}
        >
          {t("pluginManager.catalogRefresh")}
        </Button>
      </div>

      {catalogError && (
        <Alert
          type="warning"
          showIcon
          message={catalogError}
          style={{ marginBottom: 12 }}
        />
      )}

      <Spin spinning={loading}>
        {!loading && plugins.length === 0 && !catalogError && (
          <Text type="secondary">{t("pluginManager.catalogEmpty")}</Text>
        )}
        <div className={styles.catalogList}>
          {plugins.map((entry) => (
            <div className={styles.catalogRow} key={entry.id}>
              <div className={styles.catalogInfo}>
                <Space size={8} wrap>
                  <Text strong>{entry.name}</Text>
                  {entry.kind && (
                    <Tag style={{ margin: 0, textTransform: "uppercase" }}>
                      {entry.kind}
                    </Tag>
                  )}
                  {entry.installed && !entry.upgrade_available && (
                    <Tag color="success" style={{ margin: 0 }}>
                      {t("pluginManager.catalogInstalled")}
                    </Tag>
                  )}
                  {entry.upgrade_available && (
                    <Tag color="processing" style={{ margin: 0 }}>
                      {t("pluginManager.catalogUpgrade")}
                    </Tag>
                  )}
                </Space>
                {entry.description && (
                  <Text
                    type="secondary"
                    style={{ fontSize: 12, display: "block" }}
                  >
                    {entry.description}
                  </Text>
                )}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  v{entry.version}
                  {entry.size ? ` · ${entry.size}` : ""}
                  {entry.author ? ` · ${entry.author}` : ""}
                </Text>
                {entry.sha256 && (
                  <div className={styles.catalogSha256}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t("pluginManager.catalogSha256")}
                    </Text>
                    <Typography.Text
                      copyable
                      className={styles.catalogSha256Value}
                    >
                      {entry.sha256}
                    </Typography.Text>
                  </div>
                )}
              </div>
              <Button
                type={
                  entry.installed && !entry.upgrade_available
                    ? "default"
                    : "primary"
                }
                size="small"
                icon={<Download size={14} />}
                loading={installingId === entry.id}
                disabled={installingId !== null && installingId !== entry.id}
                onClick={() => void handleInstall(entry)}
              >
                {entry.upgrade_available
                  ? t("pluginManager.catalogUpgradeBtn")
                  : entry.installed
                  ? t("pluginManager.catalogReinstall")
                  : t("pluginManager.catalogInstall")}
              </Button>
            </div>
          ))}
        </div>
      </Spin>
    </div>
  );
}
