import { FolderOpenOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { BuiltinCardProps } from "./index";
import {
  parsePawAppArtifactCollectionResult,
  listPawAppArtifacts,
  type PawAppArtifactCollectionResult,
  type PawAppArtifactRef,
} from "../../../../api/modules/pawappTasks";
import { ToolCardShell } from "../shared";
import GenericToolCard from "./GenericToolCard";
import { PawAppArtifactItem } from "./PawAppTaskCard";
import styles from "./PawAppTaskCard.module.less";

function CollectionCard({
  content,
  isStreaming,
  result,
}: BuiltinCardProps & { result: PawAppArtifactCollectionResult }) {
  const { t } = useTranslation();
  const { collection } = result;
  const isCreator = result.app_id === "qwenpaw-creator";
  const title = isCreator
    ? t("tool.pawappTask.creatorLibrary")
    : t("tool.pawappTask.appLibrary", { app: result.app_id });
  const icon = isCreator ? <VideoCameraOutlined /> : <FolderOpenOutlined />;
  const [items, setItems] = useState(collection.items);
  const [nextCursor, setNextCursor] = useState(collection.next_cursor);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    setItems(collection.items);
    setNextCursor(collection.next_cursor);
    setLoadError(false);
  }, [collection]);

  const loadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setLoadError(false);
    try {
      const next = await listPawAppArtifacts(
        result.app_id,
        result.workspace_id,
        { cursor: nextCursor, limit: 25 },
      );
      setItems((current: PawAppArtifactRef[]) => {
        const seen = new Set(
          current.map((artifact) => `${artifact.artifact_id}:${artifact.version}`),
        );
        return [
          ...current,
          ...next.items.filter(
            (artifact) =>
              !seen.has(`${artifact.artifact_id}:${artifact.version}`),
          ),
        ];
      });
      setNextCursor(next.next_cursor);
    } catch {
      setLoadError(true);
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={icon}
      title={title}
      inlineResult={t("tool.pawappTask.libraryCount", {
        count: collection.total_count,
      })}
      defaultExpanded={collection.items.length > 0}
    >
      <div className={styles.body}>
        {items.length === 0 ? (
          <p>{t("tool.pawappTask.libraryEmpty")}</p>
        ) : (
          <ul className={styles.artifacts}>
            {items.map((artifact) => (
              <PawAppArtifactItem
                key={`${artifact.artifact_id}:${artifact.version}`}
                appId={result.app_id}
                workspaceId={result.workspace_id}
                artifact={artifact}
              />
            ))}
          </ul>
        )}
        {nextCursor && (
          <button
            className={styles.secondaryAction}
            type="button"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {t(
              loadingMore
                ? "tool.pawappTask.loadingMoreArtifacts"
                : "tool.pawappTask.loadMoreArtifacts",
            )}
          </button>
        )}
        {loadError && <p>{t("tool.pawappTask.libraryLoadFailed")}</p>}
      </div>
    </ToolCardShell>
  );
}

export default function PawAppArtifactCollectionCard(props: BuiltinCardProps) {
  const result = useMemo(
    () => parsePawAppArtifactCollectionResult(props.content.result),
    [props.content.result],
  );
  if (!result) return <GenericToolCard {...props} />;
  return <CollectionCard {...props} result={result} />;
}
