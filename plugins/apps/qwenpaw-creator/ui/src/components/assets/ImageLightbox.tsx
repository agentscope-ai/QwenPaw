import { Image } from "antd";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

/** Shared image viewer; keep Antd's zoom, drag, backdrop and Escape handling. */
export default function ImageLightbox({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const closeLabel = t("common.close");
  return (
    <Image
      src={src}
      alt={alt}
      style={{ display: "none" }}
      classNames={{
        popup: {
          root: "creator-image-lightbox",
          close: "creator-image-lightbox-window-close",
        },
      }}
      preview={{
        open: true,
        onOpenChange: (open) => {
          if (!open) onClose();
        },
        mask: { closable: true },
        closeIcon: (
          <span className="inline-flex items-center gap-1.5">
            <X size={18} aria-hidden="true" />
            <span>{closeLabel}</span>
          </span>
        ),
        imageRender: (originalNode) => (
          <div className="creator-image-lightbox-frame">
            {originalNode}
            <button
              type="button"
              className="creator-image-lightbox-image-close"
              aria-label={closeLabel}
              title={closeLabel}
              onMouseDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onClose();
              }}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        ),
      }}
    />
  );
}
