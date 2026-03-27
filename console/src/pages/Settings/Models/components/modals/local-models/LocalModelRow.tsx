import { memo } from "react";
import { Button, Tag, Tooltip } from "@agentscope-ai/design";
import {
  DownloadOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { LocalModelInfo } from "../../../../../../api/types";
import styles from "../../../index.module.less";
import { formatFileSize } from "./shared";

interface LocalModelRowProps {
  model: LocalModelInfo;
  currentRunningModelName: string | null;
  isModelDownloading: boolean;
  isServerBusy: boolean;
  startingModelName: string | null;
  stoppingServer: boolean;
  onStartDownload: (modelName: string) => void;
  onStartServer: (model: LocalModelInfo) => void;
  onStopServer: () => void;
}

export const LocalModelRow = memo(function LocalModelRow({
  model,
  currentRunningModelName,
  isModelDownloading,
  isServerBusy,
  startingModelName,
  stoppingServer,
  onStartDownload,
  onStartServer,
  onStopServer,
}: LocalModelRowProps) {
  const { t } = useTranslation();
  const isRunning = currentRunningModelName === model.name;
  const isStarting = startingModelName === model.name;

  return (
    <div className={styles.modelListItem}>
      <div className={styles.modelListItemInfo}>
        <span className={styles.modelListItemName}>{model.name}</span>
        <span className={styles.modelListItemId}>
          {model.id} · {formatFileSize(model.size_bytes)}
        </span>
      </div>
      <div className={styles.modelListItemActions}>
        {model.downloaded ? (
          <Tag color="green">{t("models.localDownloaded")}</Tag>
        ) : null}
        {!model.downloaded ? (
          <>
            <Button
              type="primary"
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => onStartDownload(model.id)}
              disabled={isModelDownloading || isServerBusy}
            >
              {t("common.download")}
            </Button>
            <Tooltip title={t("models.localDownloadModelFirst")}>
              <Button
                size="small"
                icon={<PlayCircleOutlined />}
                disabled
              >
                {t("models.localStartServer")}
              </Button>
            </Tooltip>
          </>
        ) : isRunning ? (
          <Button
            danger
            size="small"
            icon={<StopOutlined />}
            loading={stoppingServer}
            onClick={onStopServer}
          >
            {t("models.localStopServer")}
          </Button>
        ) : (
          <Button
            type="primary"
            size="small"
            icon={<PlayCircleOutlined />}
            loading={isStarting}
            onClick={() => onStartServer(model)}
            disabled={isModelDownloading || isServerBusy}
          >
            {t("models.localStartServer")}
          </Button>
        )}
      </div>
    </div>
  );
});