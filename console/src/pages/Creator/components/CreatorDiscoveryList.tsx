import { useTranslation } from "react-i18next";
import { Button, Card, Typography } from "antd";
import { Download } from "lucide-react";
import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import styles from "./CreatorDiscoveryList.module.less";

const { Text } = Typography;

interface CreatorDiscoveryListProps {
  apps: OfficialPluginCatalogEntry[];
  installingId: string | null;
  onInstall: (entry: OfficialPluginCatalogEntry) => void;
}

function pickLocalizedDescription(
  entry: OfficialPluginCatalogEntry,
  language: string,
): string {
  const map = entry.description_i18n;
  if (!map || Object.keys(map).length === 0) {
    return entry.description || "";
  }
  if (map[language]) return map[language];
  const prefix = language.split("-")[0].toLowerCase();
  for (const key of Object.keys(map)) {
    if (key.toLowerCase().startsWith(prefix)) return map[key];
  }
  return entry.description || "";
}

export function CreatorDiscoveryList({
  apps,
  installingId,
  onInstall,
}: CreatorDiscoveryListProps) {
  const { t, i18n } = useTranslation();

  return (
    <div className={styles.list}>
      {apps.map((entry) => {
        const isInstalling = installingId === entry.id;
        const isBusy = installingId !== null && !isInstalling;
        return (
          <Card
            key={entry.id}
            className={styles.card}
            styles={{ body: { padding: 16 } }}
          >
            <div className={styles.cardBody}>
              <div className={styles.info}>
                <Text strong className={styles.name}>
                  {entry.name}
                </Text>
                <Text type="secondary" className={styles.description}>
                  {pickLocalizedDescription(entry, i18n.language)}
                </Text>
              </div>
              <Button
                type="primary"
                size="small"
                icon={<Download size={14} />}
                loading={isInstalling}
                disabled={isBusy}
                onClick={() => onInstall(entry)}
              >
                {isInstalling ? t("creator.installing") : t("creator.install")}
              </Button>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
