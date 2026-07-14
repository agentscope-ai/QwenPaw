import React, { useMemo } from "react";
import type { ToolCallContent } from "./types";
import MediaPreview from "./MediaPreview";
import { extractAllMediaFromResult } from "./utils";
import styles from "./toolCards.module.less";

export interface ResultMediaPreviewsProps {
  content: ToolCallContent;
}

const ResultMediaPreviews: React.FC<ResultMediaPreviewsProps> = ({
  content,
}) => {
  const mediaList = useMemo(
    () => extractAllMediaFromResult(content),
    [content],
  );

  if (mediaList.length === 0) return null;

  return (
    <div className={styles.resultMediaPreviews}>
      {mediaList.map((media) => (
        <MediaPreview key={media.url} media={media} />
      ))}
    </div>
  );
};

export default ResultMediaPreviews;
