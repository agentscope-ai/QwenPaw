import { useState, type ImgHTMLAttributes } from "react";
import { useTranslation } from "react-i18next";
import ImageLightbox from "./ImageLightbox";

/** Preserve the caller's image layout while sharing the zoomable viewer. */
export default function PreviewImage({
  className,
  ...props
}: ImgHTMLAttributes<HTMLImageElement>) {
  const [visible, setVisible] = useState(false);
  const { t } = useTranslation();
  return (
    <>
      <img
        {...props}
        className={`${className ?? ""} cursor-zoom-in`}
        role="button"
        tabIndex={0}
        title={t("assets.viewFullImage")}
        onClick={(event) => {
          event.stopPropagation();
          setVisible(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            event.stopPropagation();
            setVisible(true);
          }
        }}
      />
      {visible && props.src && (
        <ImageLightbox
          src={props.src}
          alt={props.alt}
          onClose={() => setVisible(false)}
        />
      )}
    </>
  );
}
