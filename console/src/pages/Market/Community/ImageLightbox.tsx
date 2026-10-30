import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

/**
 * Fullscreen preview for body images: click the image or the mask to collapse,
 * Escape closes as well. Interaction mirrors the platform article lightbox.
 */
export function ImageLightbox({
  src,
  alt = "",
  onClose,
}: {
  src: string | null;
  alt?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  useEffect(() => {
    if (!src) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [src, onClose]);

  if (!src) return null;

  return createPortal(
    <div
      className={styles.lightboxOverlay}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={alt || t("communityPage.imagePreview")}
    >
      <img
        className={styles.lightboxImage}
        src={src}
        alt={alt}
        onClick={(event) => {
          event.stopPropagation();
          onClose();
        }}
      />
    </div>,
    document.body,
  );
}
