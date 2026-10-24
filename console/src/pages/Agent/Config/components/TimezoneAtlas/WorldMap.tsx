import { useMemo, useState, useEffect } from "react";
import { geoEquirectangular, geoPath, geoGraticule10 } from "d3-geo";
import { feature } from "topojson-client";
import land from "world-atlas/land-110m.json";
import {
  motion,
  useReducedMotion,
  useMotionValue,
  animate,
} from "motion/react";
import { Minus, Plus } from "lucide-react";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { locations } from "./locations";
import { offsetLabel } from "./timezones";
import styles from "./index.module.less";

const projection = geoEquirectangular().fitExtent(
  [
    [16, 12],
    [784, 372],
  ],
  { type: "Sphere" },
);
const path = geoPath(projection);
const landPath = path(feature(land, land.objects.land)) ?? "";
const gridPath = path(geoGraticule10()) ?? "";

export default function WorldMap({
  value,
  offset,
  onOffsetChange,
  label,
  disabled,
}: {
  value: string;
  offset: number | null;
  onOffsetChange: (minutes: number) => void;
  label: (value: string) => string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const [zoom, setZoom] = useState(1);
  const [hovered, setHovered] = useState<number | null>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  useEffect(() => {
    if (zoom !== 1) return;
    const options = reduced
      ? { duration: 0 }
      : { type: "spring" as const, stiffness: 220, damping: 30 };
    const horizontal = animate(x, 0, options);
    const vertical = animate(y, 0, options);
    return () => {
      horizontal.stop();
      vertical.stop();
    };
  }, [zoom, reduced, x, y]);
  const pins = useMemo(
    () =>
      [value].flatMap((id) => {
        const point: [number, number] | undefined =
          id === "Asia/Shanghai" ? [116.4074, 39.9042] : locations[id];
        const xy = point && projection(point);
        return xy ? [{ id, x: xy[0] / 8, y: xy[1] / 3.84 }] : [];
      }),
    [value],
  );
  return (
    <div className={styles.map}>
      <motion.div
        className={styles.geography}
        style={{ x, y }}
        animate={{ scale: zoom }}
        transition={
          reduced
            ? { duration: 0 }
            : { type: "spring", stiffness: 220, damping: 30 }
        }
        drag={zoom > 1}
        dragConstraints={{
          left: -160 * (zoom - 1),
          right: 160 * (zoom - 1),
          top: -70 * (zoom - 1),
          bottom: 70 * (zoom - 1),
        }}
        dragElastic={0.12}
        dragMomentum={false}
      >
        <svg
          viewBox="0 0 800 384"
          role="group"
          aria-label={t("agentConfig.timezone")}
        >
          <path d={gridPath} className={styles.graticule} />
          <path d={landPath} className={styles.land} />
          {Array.from({ length: 25 }, (_, index) => {
            const hours = index - 12;
            const left = Math.max(-180, hours * 15 - 7.5);
            const right = Math.min(180, hours * 15 + 7.5);
            const points = [
              ...Array.from({ length: 19 }, (_, n) => [left, -90 + n * 10]),
              ...Array.from({ length: 19 }, (_, n) => [right, 90 - n * 10]),
            ]
              .map((point) => projection(point as [number, number])!)
              .map((point) => point.join(","))
              .join(" ");
            const title = `UTC${hours >= 0 ? "+" : ""}${hours}`;
            return (
              <polygon
                key={hours}
                points={points}
                className={styles.timeBand}
                role="button"
                tabIndex={disabled ? -1 : 0}
                aria-label={title}
                onPointerEnter={() => setHovered(hours * 60)}
                onPointerLeave={() => setHovered(null)}
                onFocus={() => setHovered(hours * 60)}
                onBlur={() => setHovered(null)}
                aria-pressed={offset === hours * 60}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => {
                  if (!disabled) onOffsetChange(hours * 60);
                }}
                onKeyDown={(event) => {
                  if (
                    !disabled &&
                    (event.key === "Enter" || event.key === " ")
                  ) {
                    event.preventDefault();
                    onOffsetChange(hours * 60);
                  }
                }}
              >
                <title>{`${title} · ${t(
                  `runtimeDesign.mapPlaces.${hours}`,
                )}`}</title>
              </polygon>
            );
          })}
        </svg>
        {pins.map((pin) => (
          <div
            key={pin.id}
            className={styles.pin}
            style={{
              left: `${pin.x}%`,
              top: `${pin.y}%`,
              pointerEvents: "none",
            }}
            aria-hidden="true"
            data-selected="true"
          >
            <span />
            <span className={styles.pinLabel}>
              {pin.id === "Asia/Shanghai"
                ? t("runtimeDesign.mapPlaces.8")
                : label(pin.id)}
            </span>
          </div>
        ))}
      </motion.div>
      {hovered !== null && (
        <motion.div
          className={styles.mapPreview}
          role="status"
          initial={{ opacity: 0, y: -3 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduced ? 0 : 0.12 }}
          aria-live="polite"
        >
          <strong>{offsetLabel(hovered)}</strong>
          <span>{t(`runtimeDesign.mapPlaces.${hovered / 60}`)}</span>
        </motion.div>
      )}
      <div className={styles.zoom}>
        <Button
          aria-label={t("runtimeDesign.zoomOut")}
          disabled={zoom === 1}
          onClick={() => setZoom(1)}
          icon={<Minus size={16} />}
        />
        <Button
          aria-label={t("runtimeDesign.zoomIn")}
          disabled={zoom === 2}
          onClick={() => setZoom(2)}
          icon={<Plus size={16} />}
        />
      </div>
    </div>
  );
}
