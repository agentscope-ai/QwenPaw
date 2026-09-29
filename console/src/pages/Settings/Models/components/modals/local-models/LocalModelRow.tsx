import { memo } from "react";
import { Button } from "@agentscope-ai/design";
import {
  Trash2 as DeleteOutlined,
  Download as DownloadOutlined,
  CirclePlay as PlayCircleOutlined,
  Ban as StopOutlined,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LocalModelInfo } from "../../../../../../api/types";
import styles from "../../../index.module.less";
import prettyBytes from "pretty-bytes";

interface LocalModelRowProps {
  model: LocalModelInfo;
  currentRunningModelName: string | null;
  isModelDownloading: boolean;
  isServerBusy: boolean;
  startingModelName: string | null;
  stoppingServer: boolean;
  deletingModelName: string | null;
  onStartDownload: (model: LocalModelInfo) => void;
  onStartServer: (model: LocalModelInfo) => void;
  onStopServer: () => void;
  onDeleteModel: (model: LocalModelInfo) => void;
}

export const LocalModelRow = memo(function LocalModelRow({
  model,
  currentRunningModelName,
  isModelDownloading,
  isServerBusy,
  startingModelName,
  stoppingServer,
  deletingModelName,
  onStartDownload,
  onStartServer,
  onStopServer,
  onDeleteModel,
}: LocalModelRowProps) {
  const { t } = useTranslation();
  const isRunning = currentRunningModelName === model.id;
  const isStarting = startingModelName === model.id;
  const isDeleting = deletingModelName === model.id;

  return (
    <div className={styles.modelListItem}>
      <div className={styles.modelListItemInfo}>
        <span className={styles.modelListItemName}>{model.name}</span>
        <span className={styles.modelListItemId}>
          {model.id} · {prettyBytes(model.size_bytes)}
        </span>
      </div>
      <div className={styles.modelListItemActions}>
        {!model.downloaded ? (
          <Button
            type="primary"
            size="small"
            icon={<DownloadOutlined size="1em" />}
            onClick={() => onStartDownload(model)}
            disabled={isModelDownloading || isServerBusy}
          >
            {t("common.download")}
          </Button>
        ) : isRunning ? (
          <>
            <Button
              danger
              size="small"
              icon={<StopOutlined size="1em" />}
              loading={stoppingServer}
              onClick={onStopServer}
            >
              {t("models.localStopServer")}
            </Button>
            <Button
              danger
              size="small"
              icon={<DeleteOutlined size="1em" />}
              loading={isDeleting}
              disabled
              onClick={() => onDeleteModel(model)}
            >
              {t("common.delete")}
            </Button>
          </>
        ) : (
          <>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined size="1em" />}
              loading={isStarting}
              onClick={() => onStartServer(model)}
              disabled={isServerBusy || isDeleting}
            >
              {t("models.localStartServer")}
            </Button>
            <Button
              danger
              size="small"
              icon={<DeleteOutlined size="1em" />}
              loading={isDeleting}
              onClick={() => onDeleteModel(model)}
              disabled={isDeleting || isServerBusy}
            >
              {t("common.delete")}
            </Button>
          </>
        )}
      </div>
    </div>
  );
});
