import { useRef, useState } from "react";
import { App } from "antd";
import { ImagePlus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { communityMediaApi } from "./api";
import styles from "./index.module.less";

export type CommentImageAttachment = {
  mediaId: string;
  url: string;
  name: string;
};

export function commentMediaIds(value: CommentImageAttachment[]): string[] {
  return value.map((item) => item.mediaId).filter(Boolean);
}

const MAX_IMAGES = 5;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ACCEPT_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/gif",
  "image/webp",
]);

interface CommentImageAttachmentsProps {
  accountId: string;
  value: CommentImageAttachment[];
  onChange: (value: CommentImageAttachment[]) => void;
  onUploadingChange?: (uploading: boolean) => void;
  disabled?: boolean;
}

/** Comment composer image uploads: thumbnails + "Upload image n/5" trigger. */
export default function CommentImageAttachments({
  accountId,
  value,
  onChange,
  onUploadingChange,
  disabled = false,
}: CommentImageAttachmentsProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingIds, setDeletingIds] = useState<string[]>([]);

  const uploadFiles = async (files: File[]) => {
    let next = [...value];
    const remaining = Math.max(0, MAX_IMAGES - next.length);
    if (remaining === 0) {
      message.warning(
        t("communityPage.commentImageMax", { count: MAX_IMAGES }),
      );
      return;
    }
    const selected = files.slice(0, remaining);
    if (files.length > remaining) {
      message.warning(
        t("communityPage.commentImageMax", { count: MAX_IMAGES }),
      );
    }
    setUploading(true);
    onUploadingChange?.(true);
    try {
      for (const file of selected) {
        if (!ACCEPT_IMAGE_TYPES.has(file.type)) {
          message.error(t("communityPage.imageTypeInvalid"));
          continue;
        }
        if (file.size > MAX_IMAGE_BYTES) {
          message.error(t("communityPage.imageTooLarge"));
          continue;
        }
        try {
          const data = await communityMediaApi.upload(file, accountId);
          if (!data?.media_id || !data.url) {
            throw new Error(t("communityPage.imageUploadFailed"));
          }
          next = [
            ...next,
            { mediaId: data.media_id, url: data.url, name: file.name },
          ];
          onChange(next);
        } catch {
          message.error(t("communityPage.imageUploadFailed"));
        }
      }
    } finally {
      setUploading(false);
      onUploadingChange?.(false);
    }
  };

  const deleteImage = async (item: CommentImageAttachment) => {
    if (disabled || uploading || deletingIds.length > 0) return;
    setDeletingIds((prev) => [...prev, item.mediaId]);
    onUploadingChange?.(true);
    try {
      await communityMediaApi.remove(item.mediaId, accountId);
      onChange(value.filter((image) => image.mediaId !== item.mediaId));
    } catch {
      message.error(t("communityPage.deleteImageFailed"));
    } finally {
      setDeletingIds((prev) => prev.filter((id) => id !== item.mediaId));
      onUploadingChange?.(false);
    }
  };

  return (
    <div className={styles.attachWrap}>
      {value.length > 0 ? (
        <div className={styles.attachList}>
          {value.map((item) => (
            <div key={item.mediaId} className={styles.attachThumb}>
              <img src={item.url} alt={item.name} loading="lazy" />
              <button
                type="button"
                aria-label={t("communityPage.removeCommentImage")}
                disabled={disabled || uploading || deletingIds.length > 0}
                onClick={() => void deleteImage(item)}
                className={styles.attachRemove}
              >
                <X size={12} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {value.length < MAX_IMAGES ? (
        <button
          type="button"
          title={t("communityPage.addCommentImage")}
          disabled={disabled || uploading || deletingIds.length > 0}
          onClick={() => inputRef.current?.click()}
          className={styles.attachTrigger}
        >
          <ImagePlus size={14} aria-hidden="true" />
          <span className={styles.attachLabel}>
            {t("communityPage.addCommentImage")}
          </span>
          <span className={styles.attachCount}>
            {value.length}/{MAX_IMAGES}
          </span>
        </button>
      ) : null}
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp"
        multiple
        hidden
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          event.target.value = "";
          if (files.length) void uploadFiles(files);
        }}
      />
    </div>
  );
}
