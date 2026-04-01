import { memo } from "react";
import { Button, Tooltip } from "@agentscope-ai/design";
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
  onStartDownload: (model: LocalModelInfo) => void;
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
  const isRunning = currentRunningModelName === model.id;
  const isStarting = startingModelName === model.id;

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
          <span className={styles.modelListItemStatusButton}>
            {t("models.localDownloaded")}
          </span>
        ) : null}
        {!model.downloaded ? (
          <>
            <Button
              type="primary"
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => onStartDownload(model)}
              disabled={isModelDownloading || isServerBusy}
            >
              {t("common.download")}
            </Button>
            <Tooltip title={t("models.localDownloadModelFirst")}>
              <Button size="small" icon={<PlayCircleOutlined />} disabled>
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
            disabled={isServerBusy}
          >
            {t("models.localStartServer")}
          </Button>
        )}
      </div>
    </div>
  );
});
