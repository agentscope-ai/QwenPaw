import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, Empty, Spin, Button, Tag, Typography, Space } from "antd";
import { AppWindow, ExternalLink, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { pawappApi, type PawAppInfo } from "../../../api/modules/pawapp";
import { getApiUrl } from "../../../api/config";
import styles from "./index.module.less";

const { Text, Paragraph } = Typography;

export default function PawAppsPage() {
  const { t } = useTranslation();
  const [apps, setApps] = useState<PawAppInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedApp, setSelectedApp] = useState<PawAppInfo | null>(null);

  const fetchApps = async () => {
    setLoading(true);
    try {
      const data = await pawappApi.list();
      setApps(data.apps);
      // Auto-select first app if none selected
      if (!selectedApp && data.apps.length > 0) {
        setSelectedApp(data.apps[0]);
      }
    } catch (err) {
      console.error("Failed to fetch PawApps:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchApps();
  }, []);

  const getIframeSrc = (app: PawAppInfo): string | null => {
    if (!app.home_page) return null;
    return getApiUrl(`/pawapps/${app.id}/static/${app.home_page}`);
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.pawapps", "PawApps")}
        extra={
          <Button
            icon={<RefreshCw size={16} />}
            onClick={fetchApps}
            loading={loading}
          >
            {t("common.refresh", "Refresh")}
          </Button>
        }
      />

      <div className={styles.container}>
        {loading ? (
          <Spin
            tip={t("common.loading")}
            style={{ display: "block", margin: "10vh auto" }}
          />
        ) : apps.length === 0 ? (
          <Empty
            image={<AppWindow size={48} strokeWidth={1} />}
            description={t(
              "pawapps.noApps",
              "No PawApps installed. Install apps to ~/.copaw/apps/",
            )}
            style={{ marginTop: 48 }}
          />
        ) : (
          <div className={styles.layout}>
            {/* App List Panel */}
            <div className={styles.appList}>
              {apps.map((app) => (
                <Card
                  key={app.id}
                  className={`${styles.appCard} ${
                    selectedApp?.id === app.id ? styles.appCardActive : ""
                  }`}
                  size="small"
                  hoverable
                  onClick={() => setSelectedApp(app)}
                >
                  <Space
                    direction="vertical"
                    size={4}
                    style={{ width: "100%" }}
                  >
                    <Space align="center">
                      <Text strong>{app.name}</Text>
                      <Tag color="green" style={{ margin: 0 }}>
                        v{app.version}
                      </Tag>
                    </Space>
                    <Paragraph
                      type="secondary"
                      style={{ margin: 0, fontSize: 12 }}
                      ellipsis={{ rows: 2 }}
                    >
                      {app.description || "No description"}
                    </Paragraph>
                    {app.category && (
                      <Tag style={{ marginTop: 4 }}>{app.category}</Tag>
                    )}
                  </Space>
                </Card>
              ))}
            </div>

            {/* App Content Panel */}
            <div className={styles.appContent}>
              {selectedApp ? (
                <>
                  <div className={styles.appHeader}>
                    <Space>
                      <Text strong style={{ fontSize: 16 }}>
                        {selectedApp.name}
                      </Text>
                      <Tag color="blue">v{selectedApp.version}</Tag>
                    </Space>
                    {selectedApp.home_page && (
                      <Button
                        type="link"
                        icon={<ExternalLink size={14} />}
                        onClick={() => {
                          const src = getIframeSrc(selectedApp);
                          if (src) window.open(src, "_blank");
                        }}
                      >
                        {t("pawapps.openInNewTab", "Open in new tab")}
                      </Button>
                    )}
                  </div>
                  {selectedApp.home_page ? (
                    <iframe
                      className={styles.appIframe}
                      src={getIframeSrc(selectedApp) || ""}
                      title={selectedApp.name}
                      sandbox="allow-scripts allow-forms allow-same-origin"
                    />
                  ) : (
                    <Empty
                      description={t(
                        "pawapps.noUI",
                        "This app has no frontend UI",
                      )}
                      style={{ marginTop: 60 }}
                    />
                  )}
                </>
              ) : (
                <Empty
                  description={t("pawapps.selectApp", "Select an app to view")}
                  style={{ marginTop: 60 }}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
