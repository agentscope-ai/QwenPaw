import { useState } from "react";
import { Modal } from "antd";
import type { KnowledgeChunkAsset } from "../../../../api/types";
import styles from "../index.module.less";

type KnowledgeChunkContentProps = {
  content: string;
  assets?: KnowledgeChunkAsset[];
};

function extractImageUrls(content: string): string[] {
  const urls: string[] = [];
  const regex = /!\[.*?\]\(([^)]+)\)/g;
  let match;
  while ((match = regex.exec(content)) !== null) {
    urls.push(match[1].replace(/^file:\/\//, ""));
  }
  return urls;
}

export function KnowledgeChunkContent({
  content,
  assets = [],
}: KnowledgeChunkContentProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inlineImages = extractImageUrls(content);
  const detachedAssets = assets.filter((asset) => !content.includes(asset.url));

  return (
    <div className={styles.chunkBody}>
      <div className={styles.chunkContent}>{content}</div>
      {inlineImages.length > 0 && (
        <div className={styles.chunkThumbnails}>
          <div className={styles.chunkThumbnailsInner}>
            {inlineImages.map((url, i) => (
              <img
                key={i}
                className={styles.chunkThumbnail}
                src={url}
                alt=""
                onClick={() => setPreviewUrl(url)}
              />
            ))}
          </div>
        </div>
      )}
      {detachedAssets.length > 0 ? (
        <div className={styles.chunkAssets}>
          {detachedAssets.map((asset) =>
            asset.kind === "image" ? (
              <img
                key={asset.url}
                className={styles.chunkAssetImage}
                src={asset.url}
                alt={asset.name}
                onClick={() => setPreviewUrl(asset.url)}
              />
            ) : asset.kind === "video" ? (
              <video
                key={asset.url}
                className={styles.chunkAssetVideo}
                src={asset.url}
                controls
              />
            ) : (
              <a
                key={asset.url}
                href={asset.url}
                target="_blank"
                rel="noreferrer"
                className={styles.chunkAssetLink}
              >
                {asset.name}
              </a>
            ),
          )}
        </div>
      ) : null}
      <Modal
        open={!!previewUrl}
        footer={null}
        onCancel={() => setPreviewUrl(null)}
        width="80vw"
        centered
      >
        {previewUrl && (
          <img
            src={previewUrl}
            alt="preview"
            style={{ width: "100%", height: "auto", display: "block" }}
          />
        )}
      </Modal>
    </div>
  );
}