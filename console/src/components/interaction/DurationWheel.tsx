import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import { WheelPicker, WheelPickerWrapper } from "@ncdai/react-wheel-picker";
import "@ncdai/react-wheel-picker/style.css";
import { useTranslation } from "react-i18next";
import styles from "./DurationWheel.module.less";

const hours = Array.from({ length: 24 }, (_, value) => ({
  value,
  label: String(value).padStart(2, "0"),
}));
const minutes = Array.from({ length: 60 }, (_, value) => ({
  value,
  label: String(value).padStart(2, "0"),
}));

export function DurationWheel({
  value = 360,
  onChange,
}: {
  value?: number;
  onChange?: (value: number) => void;
}) {
  const { t } = useTranslation();
  const reducedMotion = useReducedMotion();
  const root = useRef<HTMLDivElement>(null);
  const hour = Math.min(23, Math.floor(value / 60));
  const minute = value % 60;
  useEffect(() => {
    root.current
      ?.querySelectorAll<HTMLElement>("[data-rwp]")
      .forEach((picker, index) => {
        picker.setAttribute("role", "spinbutton");
        picker.setAttribute(
          "aria-label",
          t(index === 0 ? "heartbeat.unitHours" : "heartbeat.unitMinutes"),
        );
        picker.setAttribute("aria-valuemin", "0");
        picker.setAttribute("aria-valuemax", index === 0 ? "23" : "59");
        picker.setAttribute(
          "aria-valuenow",
          String(index === 0 ? hour : minute),
        );
        picker
          .querySelectorAll("ul")
          .forEach((list) => list.setAttribute("aria-hidden", "true"));
      });
  }, [hour, minute, t]);
  return (
    <div ref={root} className={styles.duration}>
      <div className={styles.columns}>
        <div role="group" aria-label={t("heartbeat.unitHours")}>
          <WheelPickerWrapper className={styles.wheel}>
            <WheelPicker
              options={hours}
              value={hour}
              onValueChange={(next) => onChange?.(next * 60 + minute)}
              reducedMotion={!!reducedMotion}
              animateValueChanges={!reducedMotion}
              infinite
              visibleCount={8}
              optionItemHeight={72}
            />
          </WheelPickerWrapper>
          <span className={styles.unit}>{t("heartbeat.unitHours")}</span>
        </div>
        <div role="group" aria-label={t("heartbeat.unitMinutes")}>
          <WheelPickerWrapper className={styles.wheel}>
            <WheelPicker
              options={minutes}
              value={minute}
              onValueChange={(next) => onChange?.(hour * 60 + next)}
              reducedMotion={!!reducedMotion}
              animateValueChanges={!reducedMotion}
              infinite
              visibleCount={8}
              optionItemHeight={72}
            />
          </WheelPickerWrapper>
          <span className={styles.unit}>{t("heartbeat.unitMinutes")}</span>
        </div>
      </div>
    </div>
  );
}
