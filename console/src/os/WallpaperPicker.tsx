/**
 * WallpaperPicker.tsx — Overlay panel for choosing the desktop wallpaper.
 *
 * Opened from the desktop right-click menu. Lists preset wallpapers as
 * swatches; selecting one updates the persisted wallpaper store immediately.
 */
import { useTranslation } from "react-i18next";
import { X, Check } from "lucide-react";
import { WALLPAPERS } from "./wallpapers";
import { useOsWallpaper } from "./osWallpaperStore";
import { useOsStyles } from "./useOsStyles";
import { buttonRoleProps } from "./a11y";

interface WallpaperPickerProps {
  onClose: () => void;
}

export default function WallpaperPicker({ onClose }: WallpaperPickerProps) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const { wallpaperId, setWallpaper } = useOsWallpaper();

  return (
    <div
      className={styles.wpOverlay}
      role="dialog"
      aria-modal="true"
      aria-label={t("os.wallpaper", "Wallpaper")}
      onPointerDown={onClose}
    >
      <div
        className={styles.wpPanel}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <div className={styles.wpHead}>
          <span>{t("os.wallpaper", "Wallpaper")}</span>
          <button
            className={styles.wpClose}
            onClick={onClose}
            aria-label={t("common.close", "Close")}
          >
            <X size={16} />
          </button>
        </div>
        <div className={styles.wpGrid}>
          {WALLPAPERS.map((w) => (
            <div
              key={w.id}
              className={cx(
                styles.wpItem,
                wallpaperId === w.id && styles.wpItemActive,
              )}
              onClick={() => setWallpaper(w.id)}
              {...buttonRoleProps(
                () => setWallpaper(w.id),
                t(w.labelKey, w.name),
              )}
            >
              <div
                className={styles.wpSwatch}
                style={{ background: w.background }}
              >
                {wallpaperId === w.id && <Check size={18} />}
              </div>
              <span>{t(w.labelKey, w.name)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
