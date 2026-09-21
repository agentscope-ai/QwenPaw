import { useEffect, useRef, useState } from "react";
import { Button, InputNumber, Space } from "antd";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

interface Props {
  source: string;
  value: string;
  index: number;
  onChange: (value: string) => void;
  onRemove: () => void;
  disabled: boolean;
}

export function ScreenshotEditor({
  source,
  value,
  index,
  onChange,
  onRemove,
  disabled,
}: Props) {
  const { t } = useTranslation();
  const canvas = useRef<HTMLCanvasElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const [rect, setRect] = useState([0, 0, 25, 25]);
  useEffect(() => {
    let alive = true;
    const image = new Image();
    image.onload = () => {
      if (!alive || !canvas.current) return;
      canvas.current.width = image.naturalWidth;
      canvas.current.height = image.naturalHeight;
      canvas.current.getContext("2d")?.drawImage(image, 0, 0);
    };
    image.src = value;
    return () => {
      alive = false;
    };
  }, [value]);

  const mask = (x: number, y: number, width: number, height: number) => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx || disabled || !width || !height) return;
    ctx.fillStyle = "#000";
    ctx.fillRect(x, y, width, height);
    onChange(el.toDataURL("image/jpeg", 0.85));
  };
  const position = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const el = event.currentTarget;
    const bounds = el.getBoundingClientRect();
    return {
      x: ((event.clientX - bounds.left) * el.width) / bounds.width,
      y: ((event.clientY - bounds.top) * el.height) / bounds.height,
    };
  };
  return (
    <section className={styles.screenshot}>
      <canvas
        ref={canvas}
        role="img"
        aria-label={t("communityReport.screenshotPreview", {
          number: index + 1,
        })}
        className={styles.canvas}
        onPointerDown={(event) => {
          if (disabled) return;
          start.current = position(event);
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerUp={(event) => {
          if (!start.current) return;
          const end = position(event);
          const from = start.current;
          start.current = null;
          mask(
            Math.min(from.x, end.x),
            Math.min(from.y, end.y),
            Math.abs(end.x - from.x),
            Math.abs(end.y - from.y),
          );
        }}
        onPointerCancel={() => {
          start.current = null;
        }}
      />
      <p className={styles.hint}>{t("communityReport.maskHelp")}</p>
      <Space wrap>
        {rect.map((value, i) => (
          <label key={i} className={styles.coordinate}>
            {t(`communityReport.coordinate${i}`)}
            <InputNumber
              size="small"
              min={0}
              max={100}
              value={value}
              disabled={disabled}
              aria-label={t(`communityReport.coordinate${i}`)}
              onChange={(next) =>
                setRect((current) =>
                  current.map((old, j) => (j === i ? next ?? 0 : old)),
                )
              }
            />
          </label>
        ))}
        <Button
          size="small"
          disabled={disabled}
          onClick={() => {
            const el = canvas.current;
            if (el)
              mask(
                (rect[0] * el.width) / 100,
                (rect[1] * el.height) / 100,
                (rect[2] * el.width) / 100,
                (rect[3] * el.height) / 100,
              );
          }}
        >
          {t("communityReport.maskRegion")}
        </Button>
        <Button
          size="small"
          disabled={disabled}
          onClick={() => onChange(source)}
        >
          {t("communityReport.resetMasks")}
        </Button>
        <Button size="small" disabled={disabled} onClick={onRemove}>
          {t("communityReport.remove")}
        </Button>
        <a href={value} download={`feedback-screenshot-${index + 1}.jpg`}>
          {t("communityReport.downloadImage")}
        </a>
      </Space>
    </section>
  );
}
