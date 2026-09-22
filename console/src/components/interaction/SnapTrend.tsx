import { useMemo, useRef, useState } from "react";
import { Line, type LineConfig } from "@ant-design/plots";
import NumberFlow from "@number-flow/react";
import { useTheme } from "../../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import styles from "./SnapTrend.module.less";

type Point = { date: string; value: number; [key: string]: unknown };
type Chart = Parameters<NonNullable<LineConfig["onReady"]>>[0];

export function SnapTrend({
  config,
  label,
  compact = false,
}: {
  config: LineConfig;
  label: string;
  compact?: boolean;
}) {
  const { i18n } = useTranslation();
  const { isDark, previewTheme } = useTheme();
  const accent =
    (isDark ? previewTheme.dark?.accent : undefined) ??
    previewTheme.accent ??
    (isDark ? "#ff9d4d" : "#ff7f16");
  const chart = useRef<Chart | null>(null);
  const touch = useRef<number | null>(null);
  const [selected, setSelected] = useState<string>();
  const points = useMemo(
    () => (Array.isArray(config.data) ? config.data : []) as Point[],
    [config.data],
  );
  const dates = useMemo(
    () => [...new Set(points.map((p) => p.date))].sort(),
    [points],
  );
  const latestDates = useRef(dates);
  latestDates.current = dates;
  const date =
    selected && dates.includes(selected) ? selected : dates[dates.length - 1];
  const index = Math.max(0, dates.indexOf(date ?? ""));
  const seriesField =
    typeof config.colorField === "string" ? config.colorField : "model";
  const selectedPoints = points.filter((p) => p.date === date);
  const lastSelected = useRef<string>();
  const select = (next: number) => {
    const value = dates[Math.max(0, Math.min(dates.length - 1, next))];
    if (!value || lastSelected.current === value) return;
    lastSelected.current = value;
    setSelected(value);
    chart.current?.emit("tooltip:show", { data: { data: { x: value } } });
  };
  const chartElement = useMemo(
    () => (
      <Line
        {...config}
        paddingLeft={44}
        paddingRight={20}
        scale={{
          ...config.scale,
          color: {
            range: [accent, "#818b95", "#478c87", "#c49c72", "#8e7b9c"],
          },
          x: { type: "point", domain: dates, padding: 0 },
        }}
        interaction={{
          ...config.interaction,
          tooltip: { crosshairs: true, marker: true },
        }}
        onReady={(instance) => {
          chart.current = instance;
          config.onReady?.(instance);
          instance.on(
            "tooltip:show",
            (event: { data?: { data?: { x?: string }; title?: string } }) => {
              const next = event.data?.data?.x ?? event.data?.title;
              if (next && latestDates.current.includes(next)) setSelected(next);
            },
          );
        }}
      />
    ),
    [config, accent, dates],
  );
  return (
    <div className={`${styles.trend} ${compact ? styles.compact : ""}`}>
      <div className={styles.readout}>
        <time dateTime={date}>{date ?? "—"}</time>
        <div className={styles.values}>
          {selectedPoints.map((point) => (
            <span key={String(point[seriesField])}>
              <small>{String(point[seriesField] ?? label)}</small>
              {Number.isFinite(point.value) ? (
                <NumberFlow
                  value={point.value}
                  locales={compact ? "en" : i18n.language}
                  respectMotionPreference
                  format={{ notation: "compact", maximumFractionDigits: 1 }}
                  transformTiming={{ duration: 180, easing: "ease-out" }}
                />
              ) : (
                "—"
              )}
            </span>
          ))}
        </div>
      </div>
      <div
        className={styles.plot}
        data-vaul-no-drag
        onPointerDown={(event) => {
          if (event.pointerType !== "mouse" && event.isPrimary)
            touch.current = event.pointerId;
        }}
        onPointerMove={(event) => {
          if (
            event.pointerType !== "mouse" &&
            touch.current !== event.pointerId
          )
            return;
          const rect = event.currentTarget.getBoundingClientRect();
          select(
            Math.round(
              ((event.clientX - rect.left - 44) /
                Math.max(1, rect.width - 64)) *
                (dates.length - 1),
            ),
          );
        }}
        onPointerUp={() => {
          touch.current = null;
        }}
        onPointerCancel={() => {
          touch.current = null;
        }}
      >
        {chartElement}
      </div>
      {dates.length > 1 && (
        <input
          className={styles.scrubber}
          type="range"
          min={0}
          max={dates.length - 1}
          step={1}
          value={index}
          aria-label={label}
          aria-valuetext={date}
          onChange={(event) => select(Number(event.target.value))}
        />
      )}
    </div>
  );
}
