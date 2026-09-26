import { useReducedMotion } from "motion/react";
import { useLayoutEffect, useRef, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import styles from "./DurationWheel.module.less";

const ROW_HEIGHT = 72;

/** Native scrolling owns touch momentum and snapping; only settled values commit. */
function DurationColumn({
  value,
  count,
  label,
  onChange,
}: {
  value: number;
  count: number;
  label: string;
  onChange: (value: number) => void;
}) {
  const reduced = useReducedMotion();
  const root = useRef<HTMLDivElement>(null);
  const initialized = useRef(false);
  const externalScroll = useRef(false);
  const drag = useRef<{
    id: number;
    y: number;
    top: number;
    moved: boolean;
    clicked?: number;
  } | null>(null);
  const suppressClick = useRef(false);
  const wrap = (index: number) => ((index % count) + count) % count;

  useLayoutEffect(() => {
    const wheel = root.current!;
    const current = Math.round(wheel.scrollTop / ROW_HEIGHT);
    const cycle = Math.max(
      0,
      Math.min(2, Math.round((current - value) / count)),
    );
    const target = initialized.current ? cycle * count + value : count + value;
    externalScroll.current = true;
    wheel.scrollTo({
      top: target * ROW_HEIGHT,
      behavior: initialized.current && !reduced ? "smooth" : "instant",
    });
    initialized.current = true;
  }, [value, count, reduced]);

  useLayoutEffect(() => {
    const wheel = root.current!;
    const settle = () => {
      if (drag.current) return;
      const next = wrap(Math.round(wheel.scrollTop / ROW_HEIGHT));
      const userEdit = !externalScroll.current;
      externalScroll.current = true;
      // Recenter equivalent cycles without a visible jump at either boundary.
      wheel.scrollTo({ top: (count + next) * ROW_HEIGHT, behavior: "instant" });
      if (userEdit && next !== value) onChange(next);
    };
    wheel.addEventListener("scrollend", settle);
    return () => wheel.removeEventListener("scrollend", settle);
  });

  const finishDrag = (
    event: PointerEvent<HTMLDivElement>,
    cancelled = false,
  ) => {
    const active = drag.current;
    if (!active || active.id !== event.pointerId) return;
    const wheel = event.currentTarget;
    drag.current = null;
    suppressClick.current = true;
    delete wheel.dataset.dragging;
    if (wheel.hasPointerCapture(event.pointerId))
      wheel.releasePointerCapture(event.pointerId);
    if (cancelled) {
      externalScroll.current = true;
      wheel.scrollTo({
        top: (count + value) * ROW_HEIGHT,
        behavior: "instant",
      });
      return;
    }
    if (!active.moved) {
      if (active.clicked !== undefined && active.clicked !== value)
        onChange(active.clicked);
      return;
    }
    const target = Math.round(wheel.scrollTop / ROW_HEIGHT) * ROW_HEIGHT;
    externalScroll.current = false;
    if (Math.abs(wheel.scrollTop - target) < 1) {
      const next = wrap(Math.round(target / ROW_HEIGHT));
      externalScroll.current = true;
      if (next !== value) onChange(next);
    } else {
      wheel.scrollTo({ top: target, behavior: reduced ? "instant" : "smooth" });
    }
  };

  return (
    <div
      ref={root}
      className={styles.wheel}
      role="spinbutton"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={count - 1}
      aria-valuenow={value}
      onPointerDown={(event) => {
        suppressClick.current = false;
        if (event.pointerType === "mouse" && event.button === 0) {
          const wheel = event.currentTarget;
          const clicked = (event.target as HTMLElement).closest<HTMLElement>(
            "[data-value]",
          )?.dataset.value;
          drag.current = {
            id: event.pointerId,
            y: event.clientY,
            top: wheel.scrollTop,
            moved: false,
            clicked: clicked === undefined ? undefined : Number(clicked),
          };
          wheel.dataset.dragging = "true";
          wheel.setPointerCapture(event.pointerId);
          wheel.focus({ preventScroll: true });
          event.preventDefault();
        }
        root.current!.scrollTo({
          top: root.current!.scrollTop,
          behavior: "instant",
        });
        externalScroll.current = false;
      }}
      onPointerMove={(event) => {
        const active = drag.current;
        if (!active || active.id !== event.pointerId) return;
        const delta = active.y - event.clientY;
        if (!active.moved && Math.abs(delta) < 3) return;
        active.moved = true;
        const cycle = count * ROW_HEIGHT;
        const top = active.top + delta;
        const centered = cycle + (((top % cycle) + cycle) % cycle);
        event.currentTarget.scrollTop = centered;
        active.top = centered;
        active.y = event.clientY;
      }}
      onPointerUp={(event) => finishDrag(event)}
      onPointerCancel={(event) => finishDrag(event, true)}
      onLostPointerCapture={(event) => finishDrag(event, true)}
      onClickCapture={(event) => {
        if (suppressClick.current) {
          event.preventDefault();
          event.stopPropagation();
          suppressClick.current = false;
        }
      }}
      onWheel={() => {
        externalScroll.current = false;
      }}
      onKeyDown={(event) => {
        const offset =
          event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
        if (!offset && event.key !== "Home" && event.key !== "End") return;
        event.preventDefault();
        const next =
          event.key === "Home"
            ? 0
            : event.key === "End"
            ? count - 1
            : wrap(value + offset);
        onChange(next);
      }}
    >
      <div aria-hidden="true">
        {Array.from({ length: count * 3 }, (_, index) => (
          <div
            key={index}
            data-value={wrap(index)}
            className={styles.option}
            onClick={() => onChange(wrap(index))}
          >
            {String(wrap(index)).padStart(2, "0")}
          </div>
        ))}
      </div>
    </div>
  );
}

export function DurationWheel({
  value = 360,
  onChange,
  disabled = false,
  maxHours = 23,
}: {
  maxHours?: number;
  disabled?: boolean;
  value?: number;
  onChange?: (value: number) => void;
}) {
  const { t } = useTranslation();
  const hour = Math.min(maxHours, Math.floor(value / 60));
  const minute = value % 60;
  const columns = [
    {
      value: hour,
      count: maxHours + 1,
      label: t("heartbeat.unitHours"),
      change: (next: number) => onChange?.(next * 60 + minute),
    },
    {
      value: minute,
      count: 60,
      label: t("heartbeat.unitMinutes"),
      change: (next: number) => onChange?.(hour * 60 + next),
    },
  ];
  return (
    <div className={styles.duration} aria-disabled={disabled}>
      <div className={styles.columns}>
        {columns.map((column, index) => (
          <div key={index} role="group" aria-label={column.label}>
            {disabled ? (
              <span className={styles.disabledValue}>
                {String(column.value).padStart(2, "0")}
              </span>
            ) : (
              <DurationColumn
                value={column.value}
                count={column.count}
                label={column.label}
                onChange={column.change}
              />
            )}
            <span className={styles.unit}>{column.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
