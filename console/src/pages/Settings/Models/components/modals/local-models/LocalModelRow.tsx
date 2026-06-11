import { memo } from "react";
import { Button } from "@/components/ui/button";
import { Download, Play, Square, Trash2 } from "lucide-react";
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
            size="sm"
            onClick={() => onStartDownload(model)}
            disabled={isModelDownloading || isServerBusy}
          >
            <Download className="mr-1 h-3 w-3" />
            {t("common.download")}
          </Button>
        ) : isRunning ? (
          <>
            <Button
              variant="destructive"
              size="sm"
              disabled={stoppingServer}
              onClick={onStopServer}
            >
              <Square className="mr-1 h-3 w-3" />
              {t("models.localStopServer")}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled
              onClick={() => onDeleteModel(model)}
            >
              <Trash2 className="mr-1 h-3 w-3" />
              {t("common.delete")}
            </Button>
          </>
        ) : (
          <>
            <Button
              size="sm"
              disabled={isStarting || isServerBusy || isDeleting}
              onClick={() => onStartServer(model)}
            >
              <Play className="mr-1 h-3 w-3" />
              {t("models.localStartServer")}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={isDeleting || isServerBusy}
              onClick={() => onDeleteModel(model)}
            >
              <Trash2 className="mr-1 h-3 w-3" />
              {t("common.delete")}
            </Button>
          </>
        )}
      </div>
    </div>
  );
});
