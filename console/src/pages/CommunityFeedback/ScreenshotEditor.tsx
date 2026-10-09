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
  const [selection, setSelection] = useState<number[] | null>(null);
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
      x: Math.max(
        0,
        Math.min(
          el.width,
          ((event.clientX - bounds.left) * el.width) / bounds.width,
        ),
      ),
      y: Math.max(
        0,
        Math.min(
          el.height,
          ((event.clientY - bounds.top) * el.height) / bounds.height,
        ),
      ),
    };
  };
  return (
    <section className={styles.screenshot}>
      <div className={styles.maskCanvas}>
        <canvas
          ref={canvas}
          role="img"
          aria-label={t("communityReport.screenshotPreview", {
            number: index + 1,
          })}
          className={styles.canvas}
          onPointerDown={(event) => {
            if (disabled || event.button !== 0) return;
            event.preventDefault();
            start.current = position(event);
            setSelection(null);
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            const from = start.current;
            if (!from || disabled) return;
            const end = position(event);
            const el = event.currentTarget;
            setSelection([
              (Math.min(from.x, end.x) / el.width) * 100,
              (Math.min(from.y, end.y) / el.height) * 100,
              (Math.abs(end.x - from.x) / el.width) * 100,
              (Math.abs(end.y - from.y) / el.height) * 100,
            ]);
          }}
          onPointerUp={(event) => {
            if (!start.current) return;
            const end = position(event);
            const from = start.current;
            start.current = null;
            setSelection(null);
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              event.currentTarget.releasePointerCapture(event.pointerId);
            mask(
              Math.min(from.x, end.x),
              Math.min(from.y, end.y),
              Math.abs(end.x - from.x),
              Math.abs(end.y - from.y),
            );
          }}
          onPointerCancel={() => {
            start.current = null;
            setSelection(null);
          }}
          onLostPointerCapture={() => {
            start.current = null;
            setSelection(null);
          }}
        />
        {selection && (
          <div
            className={styles.maskSelection}
            aria-hidden="true"
            style={{
              left: `${selection[0]}%`,
              top: `${selection[1]}%`,
              width: `${selection[2]}%`,
              height: `${selection[3]}%`,
            }}
          />
        )}
      </div>
      <p className={styles.hint}>{t("communityReport.maskHelp")}</p>
      <details className={styles.maskOptions}>
        <summary>{t("communityAssist.preciseMask")}</summary>
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
        </Space>
      </details>
      <Space wrap>
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
